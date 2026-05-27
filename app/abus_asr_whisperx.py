import os
import sys
import platform

import time
import numpy as np
from typing import BinaryIO, Union, Tuple, List, Optional
from io import StringIO
import re

import whisper
import whisperx
from whisperx.utils import get_writer
import gc 
import ctranslate2
import whisper
import torch
import gradio as gr

from app.abus_path import *
from app.abus_asr_parameters import *


import structlog
logger = structlog.get_logger()


class ProgressCapture(StringIO):
    def __init__(self, progress, desc):
        super().__init__()
        self.progress = progress
        self.desc = desc

    def write(self, text):
        # 진행률 출력 패턴: "Progress: XX.XX%..."
        match = re.search(r"Progress: (\d+\.\d+)%", text)
        if match and self.progress is not None:
            percent = float(match.group(1)) / 100  # 0~1 사이 값으로 변환
            self.progress(percent, desc=self.desc)
        super().write(text)

    def flush(self):
        pass  # Gradio에서 불필요
    

class WhisperXInference:
    def __init__(self):
        self.set_environment()
        
        self.current_model_size = None
        self.model = None
        self.translatable_models = ["large", "large-v1", "large-v2", "large-v3"]
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.current_compute_type = "default"        
        

    @staticmethod
    def set_environment():
        system = platform.system()
        if system != "Windows":
            return
                
        current_path = os.environ.get('PATH', '')
        conda_prefix = os.environ.get('CONDA_PREFIX', '')

        # cudnn bin 폴더의 경로
        cudnn_bin_path = os.path.join(conda_prefix, 'Lib', 'site-packages', 'nvidia', 'cudnn', 'bin')

        # PATH에 cudnn bin 경로가 없으면 추가
        if cudnn_bin_path not in current_path:
            new_path = f"{current_path};{cudnn_bin_path}"
            os.environ['PATH'] = new_path
            logger.debug(f"[abus_asr_whisperx.py] set_environment - PATH에 다음 경로가 추가되었습니다: {cudnn_bin_path}")

            # 사용자 환경변수에 영구 저장
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_ALL_ACCESS)
            winreg.SetValueEx(key, 'PATH', 0, winreg.REG_EXPAND_SZ, new_path)
            winreg.CloseKey(key)     


        # sys.path에도 추가 (Python 모듈 검색 경로)
        if cudnn_bin_path not in sys.path:
            sys.path.append(cudnn_bin_path)
            logger.debug(f"[abus_asr_whisperx.py] set_environment - sys.path에 다음 경로가 추가되었습니다: {cudnn_bin_path}")
        
        
    @staticmethod
    def release_cuda_memory():
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.reset_max_memory_allocated()
            logger.debug(f'[abus_asr_whisperx.py] release_cuda_memory - OK!! ')

    @staticmethod
    def remove_input_files(file_paths: List[str]):
        if not file_paths:
            return

        for file_path in file_paths:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
    
    
    @staticmethod
    def available_models():
        return whisper.available_models()
    
    @staticmethod
    def available_langs():
        return sorted(list(whisper.tokenizer.LANGUAGES.values()))    
    
    
    @staticmethod
    def available_compute_types():
        types_orderd = []
        types = None
        if torch.cuda.is_available():
            types = ctranslate2.get_supported_compute_types('cuda')
        else:
            types = ctranslate2.get_supported_compute_types('cpu')
        
        logger.debug(f'[abus_asr_whisperx.py] available_compute_types - types = {types} ')
            
        if 'float32' in types: types_orderd.append('float32')
        if 'float16' in types: types_orderd.append('float16')
        if 'int16_float32' in types: types_orderd.append('int16_float32')
        if 'int16_float16' in types: types_orderd.append('int16_float16')
        if 'int8_float32' in types: types_orderd.append('int8_float32')
        if 'int8_float16' in types: types_orderd.append('int8_float16')
        if 'int16' in types: types_orderd.append('int16')
        if 'int8' in types: types_orderd.append('int8')
        
        return types_orderd
           
        
                
                
    def transcribe_live(self,
                        input_sample: np.ndarray,
                        params: WhisperParameters,
                        progress=None
                        ) -> Tuple[List[dict], float]:
        try:
            denoise_sample = self._denoise_live(input_sample, params.denoise_level)
            result, time_for_task = self.transcribe(denoise_sample, params.copy(), progress)
            return result, time_for_task

        except Exception as e:
            logger.error(f"[abus_asr_whisperx.py] transcribe_live - An error occurred: {e}")
            return None, None
        finally:
            self.release_cuda_memory()            
                        

    def transcribe_file(self,
                        input_path: str,
                        params: WhisperParameters,
                        highlight_words: bool,
                        progress=None,
                        ) -> list:
        try:
            result, time_for_task = self.transcribe(input_path, params.copy(), progress)
            subtitles = self.generate_and_write_file(input_path, result, highlight_words)                            
            return subtitles
        except Exception as e:
            logger.error(f"[abus_asr_whisperx.py] transcribe_file - An error occurred: {e}")
            raise
        finally:
            self.model = None
            self.release_cuda_memory()
            
        
        
    def transcribe(self,
                   audio: Union[str, BinaryIO, np.ndarray],
                   params: WhisperParameters,
                   progress: gr.Progress
                   ) -> Tuple[List[dict], float]:

        start_time = time.time()        
        
        if params.lang == "Automatic Detection":
            params.lang = None
        else:
            language_code_dict = {value: key for key, value in whisper.tokenizer.LANGUAGES.items()}
            params.lang = language_code_dict[params.lang]        
        
        if params.model_size != self.current_model_size or self.model is None or params.compute_type != self.current_compute_type:
            self.update_model(params, progress)
            
        original_stdout = sys.stdout
        sys.stdout = ProgressCapture(progress, "Transcribing...")            
        try:
            result = self.model.transcribe(
                    audio=audio,
                    language=params.lang,
                    task="translate" if params.is_translate and self.current_model_size in self.translatable_models else "transcribe",
                    print_progress=True,
                    verbose=False 
                    )
        finally:        
            sys.stdout = original_stdout


        original_stdout = sys.stdout
        sys.stdout = ProgressCapture(progress, "Alignment...")    
        try:
            model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=self.device)
            result = whisperx.align(result["segments"], model_a, metadata, audio, self.device,
                                    interpolate_method="nearest",   # "nearest", "linear", "ignore"
                                    return_char_alignments=True,
                                    print_progress=True
                                    )
            result["language"] = params.lang
            del model_a        
        finally:
            sys.stdout = original_stdout
            
                   
        elapsed_time = time.time() - start_time
        return result, elapsed_time    
        

    def update_model(self,
                    params: WhisperParameters,
                    progress: gr.Progress
                    ):
 
        if progress is not None: 
            progress(0, desc="Initializing Model..")
            
        self.current_model_size = params.model_size
        self.current_compute_type = params.compute_type
        
        asr_options = {
            "beam_size": params.beam_size,
            "patience": params.patience,
            # "length_penalty": params.length_penalty,
            "temperatures": params.temperature,
            # "compression_ratio_threshold": params.compression_ratio_threshold,
            # "log_prob_threshold": params.logprob_threshold,
            "no_speech_threshold": params.no_speech_threshold,
            "condition_on_previous_text": params.condition_on_previous_text,
            "initial_prompt": params.initial_prompt,
            # "suppress_tokens": [int(x) for x in args.pop("suppress_tokens").split(",")],
            # "suppress_numerals": params.suppress_numerals,
        }        
        
        
        self.model = whisperx.load_model(
            whisper_arch=params.model_size,
            device=self.device,
            compute_type=params.compute_type,
            download_root=os.path.join("model", "faster-whisper"),
            asr_options=asr_options
        )
        


    def _denoise_live(self, input: np.ndarray, denoise_level: int = 0) -> np.ndarray:
        logger.debug(f'[abus_asr_whisperx.py] _denoise_live:input.shape = {input.shape}') 

        return input



    @staticmethod
    def generate_and_write_file(input_path: str, 
                                result, highlight_words: bool) -> list:
        subtitles = []
        if len(result['segments']) < 1:
            return subtitles   
            
        try:
            # subs = SSAFile()
            # for segment in result['segments']:
            #     event = SSAEvent(start=pysubs2.make_time(s=segment["start"]), end=pysubs2.make_time(s=segment["end"]), name="")
            #     event.plaintext = segment["text"].strip()
            #     subs.append(event)            
                        
            # vtt_path = path_change_ext(input_path, '.vtt')        
            # subs.save(vtt_path)    
            # subtitles.append(vtt_path)  
            
            # ass_path = path_change_ext(input_path, '.ass')        
            # subs.save(ass_path)
            # subtitles.append(ass_path)         
            
            # txt_path = path_change_ext(input_path, '.txt')
            # txt_content = get_txt(result['segments'])
            # write_file(txt_content, txt_path)
            # subtitles.append(txt_path)                                     

            # if highlight_words == True:
            #     srt_path = path_change_ext(input_path, '.srt')            
            #     ts_contents = get_srt_wordlevel(result['segments'])
            #     write_file(ts_contents, srt_path)
            #     subtitles.append(srt_path)
            # else:
            #     srt_path = path_change_ext(input_path, '.srt')
            #     subs.save(srt_path)
            #     subtitles.append(srt_path)           
            
            output_dir = os.path.dirname(input_path)    
            writer = get_writer("all", output_dir)
            writer_args = {"highlight_words": highlight_words, "max_line_count": None, "max_line_width": None}    
            writer(result, input_path, writer_args)
            
            vtt_path = path_change_ext(input_path, '.vtt')     
            tsv_path = path_change_ext(input_path, '.tsv')
            txt_path = path_change_ext(input_path, '.txt')
            srt_path = path_change_ext(input_path, '.srt')
            json_path = path_change_ext(input_path, '.json')
            
            if os.path.exists(vtt_path):
                subtitles.append(vtt_path)
            if os.path.exists(tsv_path):
                subtitles.append(tsv_path)
            if os.path.exists(txt_path):
                subtitles.append(txt_path)
            if os.path.exists(srt_path):
                subtitles.append(srt_path)
            if os.path.exists(json_path):
                subtitles.append(json_path)
                
            return subtitles
        except Exception as e:
            logger.error(f"[abus_asr_whisperx.py] generate_and_write_file - An error occurred: {e}")

        finally:
            return subtitles
    

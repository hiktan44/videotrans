import os
import sys
import platform


import time
import numpy as np
from typing import BinaryIO, Union, Tuple, List, Optional
from datetime import datetime

import faster_whisper
import gc
import ctranslate2
import whisper
import torch
import gradio as gr
import pysubs2       



from app.abus_subtitle import get_srt, get_vtt, get_txt, write_file, get_srt_wordlevel, get_vtt_block
from app.abus_path import *
from app.abus_asr_parameters import *

import structlog
logger = structlog.get_logger()


class FasterWhisperInference:
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
            logger.debug(f"[abus_asr_faster_whisper.py] set_environment - PATH에 다음 경로가 추가되었습니다: {cudnn_bin_path}")

            # 사용자 환경변수에 영구 저장
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0, winreg.KEY_ALL_ACCESS)
            winreg.SetValueEx(key, 'PATH', 0, winreg.REG_EXPAND_SZ, new_path)
            winreg.CloseKey(key)     


        # sys.path에도 추가 (Python 모듈 검색 경로)
        if cudnn_bin_path not in sys.path:
            sys.path.append(cudnn_bin_path)
            logger.debug(f"[abus_asr_faster_whisper.py] set_environment - sys.path에 다음 경로가 추가되었습니다: {cudnn_bin_path}")
        
        
    @staticmethod
    def release_cuda_memory():
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.reset_max_memory_allocated()
            logger.debug(f'[abus_asr_faster_whisper.py] release_cuda_memory - OK!! ')

    @staticmethod
    def remove_input_files(file_paths: List[str]):
        if not file_paths:
            return

        for file_path in file_paths:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
    
    
    @staticmethod
    def available_models():
        return faster_whisper.utils.available_models()
    
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
        
        logger.debug(f'[abus_asr_faster_whisper.py] available_compute_types - types = {types} ')
            
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
            transcribed_segments, time_for_task = self.transcribe(denoise_sample, params.copy(), progress)
            return transcribed_segments, time_for_task

        except Exception as e:
            logger.error(f"[abus_asr_faster_whisper.py] transcribe_live - An error occurred: {e}")
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
            transcribed_segments, time_for_task = self.transcribe(input_path, params.copy(), progress)
            subtitles = self.generate_and_write_file(input_path, transcribed_segments, highlight_words)
                        
            return subtitles
        except Exception as e:
            logger.error(f"[abus_asr_faster_whisper.py] transcribe_file - An error occurred: {e}")
        finally:
            self.model = None
            self.release_cuda_memory()
            
        
        
    def transcribe(self,
                   audio: Union[str, BinaryIO, np.ndarray],
                   params,                   
                   progress: gr.Progress
                   ) -> Tuple[List[dict], float]:

        start_time = time.time()
        
        if params.model_size != self.current_model_size or self.model is None or params.compute_type != self.current_compute_type:
            self.update_model(params.model_size, params.compute_type, progress)

        if params.lang == "Automatic Detection":
            params.lang = None
        else:
            language_code_dict = {value: key for key, value in whisper.tokenizer.LANGUAGES.items()}
            params.lang = language_code_dict[params.lang]

        segments, info = self.model.transcribe(
                audio=audio,
                language=params.lang,
                task="translate" if params.is_translate and self.current_model_size in self.translatable_models else "transcribe",
                vad_filter=params.vad_filter,
                beam_size=params.beam_size,
                log_prob_threshold=params.log_prob_threshold,
                no_speech_threshold=params.no_speech_threshold,                
                best_of=params.best_of,
                patience=params.patience,                
                condition_on_previous_text=params.condition_on_previous_text,
                temperature=params.temperature,
                word_timestamps=params.word_timestamps,
                hallucination_silence_threshold=params.hallucination_silence_threshold,
                repetition_penalty=params.repetition_penalty,
                vad_parameters=params.vad_parameters,
                initial_prompt=params.initial_prompt       
                )
        
        if progress is not None: 
            progress(0, desc="Loading audio..")


        segments_result = []
        for segment in segments:
            if progress is not None: 
                progress(segment.start / info.duration, desc="Transcribing...")
            segment_dict = {'start':segment.start,'end':segment.end,'text':segment.text, 'words':segment.words}
            segments_result.append(segment_dict)    
            
           
        elapsed_time = time.time() - start_time
        return segments_result, elapsed_time    
        

    def update_model(self,
                     model_size: str,
                     compute_type: str,
                     progress: gr.Progress
                     ):
     
        if progress is not None: 
            progress(0, desc="Initializing Model..")
            
        self.current_model_size = model_size
        self.current_compute_type = compute_type
        
        
        self.model = faster_whisper.WhisperModel(
            device=self.device,
            model_size_or_path=model_size,
            download_root=os.path.join("model", "faster-whisper"),
            compute_type=self.current_compute_type,
            cpu_threads=min(4, os.cpu_count() or 1),
            num_workers=1
        )
        


    def _denoise_live(self, input: np.ndarray, denoise_level: int = 0) -> np.ndarray:
        logger.debug(f'[abus_asr_faster_whisper.py] _denoise_live:input.shape = {input.shape}') 

        return input



    @staticmethod
    def generate_and_write_file(input_path: str, 
                                transcribed_segments: list, highlight_words: bool) -> list:
        subtitles = []   
        if len(transcribed_segments) < 1:
            return subtitles
                 
        try:
            transcribed_segments = FasterWhisperInference._clean_repeated_segments(transcribed_segments)
            subs = pysubs2.load_from_whisper(transcribed_segments)

            vtt_path = path_change_ext(input_path, '.vtt')        
            subs.save(vtt_path)    
            subtitles.append(vtt_path)
            logger.debug(f'[abus_asr_faster_whisper.py] generate_and_write_file - append {vtt_path}')
            
            ass_path = path_change_ext(input_path, '.ass')        
            subs.save(ass_path)
            subtitles.append(ass_path)
            logger.debug(f'[abus_asr_faster_whisper.py] generate_and_write_file - append {ass_path}')

            txt_path = path_change_ext(input_path, '.txt')
            txt_content = get_txt(transcribed_segments)
            write_file(txt_content, txt_path)
            subtitles.append(txt_path)
            logger.debug(f'[abus_asr_faster_whisper.py] generate_and_write_file - append {txt_path}')

            if highlight_words == True:
                srt_path = path_change_ext(input_path, '.srt')
                ts_contents = get_srt_wordlevel(transcribed_segments)
                write_file(ts_contents, srt_path)
                subtitles.append(srt_path)
                logger.debug(f'[abus_asr_faster_whisper.py] generate_and_write_file - append {srt_path}')                
            else:
                # srt_path = path_change_ext(input_path, '.srt')
                # subs.save(srt_path)
                # subtitles.append(srt_path)
                
                srt_path = path_change_ext(input_path, '.srt')
                srt_content = get_srt(transcribed_segments)
                write_file(srt_content, srt_path)
                subtitles.append(srt_path)
                logger.debug(f'[abus_asr_faster_whisper.py] generate_and_write_file - append {srt_path}')                                                
                
            return subtitles
        except Exception as e:
            logger.error(f"[abus_asr_faster_whisper.py] generate_and_write_file - An error occurred: {e}")

        finally:
            return subtitles

    @staticmethod
    def _clean_repeated_segments(transcribed_segments: list) -> list:
        cleaned = []
        last_text = ""
        repeat_count = 0

        for segment in transcribed_segments:
            text = (segment.get("text") or "").strip()
            normalized = " ".join(text.lower().split())
            duration = float(segment.get("end", 0) or 0) - float(segment.get("start", 0) or 0)

            if normalized and normalized == last_text:
                repeat_count += 1
                if repeat_count >= 2 or duration <= 2.5:
                    continue
            else:
                repeat_count = 0

            segment["text"] = FasterWhisperInference._collapse_repeated_phrases(text)
            cleaned.append(segment)
            last_text = normalized

        return cleaned

    @staticmethod
    def _collapse_repeated_phrases(text: str) -> str:
        words = text.split()
        if len(words) < 3:
            return text

        collapsed = []
        i = 0
        while i < len(words):
            phrase_len = 1
            replaced = False
            while phrase_len <= 4 and i + phrase_len * 3 <= len(words):
                phrase = words[i:i + phrase_len]
                repeats = 1
                while words[i + repeats * phrase_len:i + (repeats + 1) * phrase_len] == phrase:
                    repeats += 1
                if repeats >= 3:
                    collapsed.extend(phrase)
                    i += repeats * phrase_len
                    replaced = True
                    break
                phrase_len += 1
            if not replaced:
                collapsed.append(words[i])
                i += 1

        return " ".join(collapsed)
    

        



import json
import subprocess
import sys
import tempfile
from pathlib import Path

from src.config import UserConfig

from app.abus_downloader import *
from app.abus_ffmpeg import *
from app.abus_demucs import *
from app.abus_genuine import *
from app.abus_files import *

from app.abus_asr_faster_whisper import *
from app.abus_asr_whisper import *
from app.abus_asr_whisper_timestamped import *
from app.abus_asr_whisperx import *
from app.abus_openai import *
from app.abus_zai import *

from src.i18n.i18n import I18nAuto
i18n = I18nAuto()


class GradioASR:
    def __init__(self, user_config: UserConfig):
        self.user_config = user_config
        
        self.fm = FileManager()
        
        self.downloader = YoutubeDownloader()
        
        asr_engine = self.user_config.get("asr_engine", 'faster-whisper')
        self.whisper_inf = self.switch_case(asr_engine)   
        
        # self.mdxnet_models_dir = os.path.join(os.getcwd(), 'model', 'mdxnet-model')
        # with open(os.path.join(self.mdxnet_models_dir, 'model_data.json')) as infile:
        #     self.mdx_model_params = json.load(infile)
    
    def switch_case(self, case):
        switch_dict = {
            'faster-whisper': lambda: FasterWhisperInference(),
            'whisper': lambda: WhisperInference(),
            'whisper-timestamped': lambda: WhisperTimestampedInference(),
            'whisperX': lambda: WhisperXInference(),
            'openai-transcribe': lambda: OpenAITranscribeInference(),
            'zai-transcribe': lambda: ZAITranscribeInference()
        }
        return switch_dict.get(case, lambda: FasterWhisperInference())()    
    
        

    def open_workspace_folder(self):
        cmd_open_explorer(path_workspace_folder())
    
    def open_temp_folder(self):
        cmd_open_explorer(path_gradio_folder())
    
    # def open_model_folder(self):
    #     cmd_open_explorer(self.mdxnet_models_dir)
        
    def get_asr_engines(self):
        return ['faster-whisper', 'openai-transcribe', 'zai-transcribe', 'whisper', 'whisper-timestamped', 'whisperX']        
    
    def update_whisper_models(self, asr_engine):
        whisper_inf = self.switch_case(asr_engine)       
        model_list = whisper_inf.available_models()
        if len(model_list) > 0:
            model_name = self.user_config.get(f'{asr_engine.replace("-", "_")}_model', 'large')
            return gr.update(choices=model_list, value=model_name)
        
        return gr.update(choices=[], value=None)    
    
    
    def get_whisper_models(self):
        return self.whisper_inf.available_models()

        
    def get_whisper_languages(self):
        return self.whisper_inf.available_langs()
        
    def get_whisper_compute_types(self):
        return FasterWhisperInference.available_compute_types()
        
    # return Video, Audio, File    
    def upload_source(self, 
                      file_obj, mic_file, youtube_url: str, video_quality: str, audio_format: str):
        self.user_config.set("video_quality", video_quality)
        self.user_config.set("audio_format", audio_format)

        try:
            logger.debug(f'upload_source: file_obj={file_obj}, mic_file={mic_file}, youtube_url={youtube_url}')
            self.fm = FileManager()
            if self._upload(file_obj, mic_file, youtube_url, video_quality, audio_format) == False:
                return None, None

            return self.fm.get_split("Source.video"), self.fm.get_split("Source.audio")
        except Exception as e:
            logger.error(f"[gradio_asr.py] upload_source - An error occurred: {e}")
            gr.Warning(f'{e}')
            return None, None

    def _upload(self,
                file_obj, mic_file, youtube_url: str, video_quality: str, audio_format: str):
        if (file_obj is not None):
            uploaded_file = cmd_copy_file_to(file_obj.name, path_workspace_subfolder(file_obj.name))
        elif mic_file and mic_file.strip():
            uploaded_file = cmd_copy_file_to(mic_file, path_workspace_subfolder(mic_file))
        elif youtube_url and youtube_url.strip():
            youtube_file = self.downloader.yt_download(youtube_url, path_youtube_folder(), video_quality)
            uploaded_file = cmd_copy_file_to(youtube_file, path_workspace_subfolder(youtube_file))
        else:
            return False
        
        self.source_file = uploaded_file
            
        
        self.has_audio, self.has_video = ffmpeg_codec_type(self.source_file)
        logger.debug(f'upload_source: source_file={self.source_file}, has_audio={self.has_audio}, has_video={self.has_video}')
        if self.has_audio == False:     # error
            return False
        elif self.has_video == False:   # audio-only
            self.fm.set_split("Source.video", None)
            self.fm.set_split("Source.audio", self.source_file)   
        else:
            input_audio_file = path_change_ext(self.source_file, f'.{audio_format}')
            ffmpeg_extract_audio(self.source_file, input_audio_file, audio_format)    
            self.fm.set_split("Source.video", self.source_file)
            self.fm.set_split("Source.audio", input_audio_file)
        return True
    
    def gradio_whisper_default(self):
        return ["small", "Automatic Detection", "int8", False, 0]
   
    def transcribe(self,
                  asr_engine, modelName, whisper_language, compute_type, highlight_words, denoise_level):
        self.user_config.set("asr_engine", asr_engine)
        self.user_config.set(f'{asr_engine.replace("-", "_")}_model', modelName)
        self.user_config.set("whisper_language", whisper_language)
        self.user_config.set("whisper_compute_type", compute_type)
        self.user_config.set("whisper_highlight_words", highlight_words)
        self.user_config.set("denoise_level", denoise_level)        
        
        try: 
            source_audio = self.fm.get_split("Source.audio")
            if not source_audio or not os.path.exists(source_audio):
                raise ValueError("Audio is not ready yet. Please wait until the media upload/download finishes, then run Whisper again.")

            denoise_inst_path, denoise_vocal_path = self._denoise(source_audio, denoise_level)
            input_path = denoise_vocal_path if os.path.exists(denoise_vocal_path) else source_audio
            if not input_path or not os.path.exists(input_path):
                raise ValueError("Audio file was not created. Please upload/download the media again.")

            logger.debug(f'transcribe : input_path = {input_path}')

            supported_compute_types = self.get_whisper_compute_types()
            if compute_type not in supported_compute_types:
                fallback_compute_type = 'int8' if 'int8' in supported_compute_types else supported_compute_types[0]
                logger.warning(
                    f"[gradio_asr.py] transcribe - Unsupported compute_type={compute_type}; "
                    f"falling back to {fallback_compute_type}"
                )
                compute_type = fallback_compute_type
            
            params = WhisperParameters(model_size=modelName, 
                                       lang=whisper_language if whisper_language == "Automatic Detection" else whisper_language.lower(), 
                                       compute_type=compute_type)
            
            if asr_engine == 'faster-whisper':
                subtitles = self._transcribe_faster_whisper_subprocess(input_path, params, highlight_words)
            else:
                self.whisper_inf = self.switch_case(asr_engine)
                subtitles = self.whisper_inf.transcribe_file(input_path, params, highlight_words, gr.Progress())
            self.fm.set_subtitles(subtitles, whisper_language, source_audio) 
            srt_file = self.fm.get_subtitle('.srt')
            srt_string = self._read_subtitle_file(srt_file)
            logger.debug(f'srt_file = {srt_file}, self.source_file = {self.source_file}')
                        
            if(self.has_video and ffmpeg_browser_compatible(self.source_file)):
                if srt_file:
                    return (self.source_file, srt_file), srt_string, self.fm.get_all_files()
                else:
                    return self.source_file, srt_string, self.fm.get_all_files()      
            else:
                return None, srt_string, self.fm.get_all_files()  
            
        except Exception as e:
            logger.error(f"[gradio_asr.py] transcribe - An error occurred: {e}")
            gr.Warning(f'{e}')
            return None, None, None            

    def _transcribe_faster_whisper_subprocess(self, input_path, params, highlight_words):
        worker_path = Path(__file__).resolve().parent / "asr_worker.py"
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as output_file:
            output_json = output_file.name

        cmd = [
            sys.executable,
            str(worker_path),
            "--input",
            input_path,
            "--output",
            output_json,
            "--model",
            params.model_size,
            "--language",
            params.lang,
            "--compute-type",
            params.compute_type,
        ]
        if highlight_words:
            cmd.append("--highlight-words")

        env = os.environ.copy()
        env.setdefault("OMP_NUM_THREADS", "4")
        env.setdefault("MKL_NUM_THREADS", "4")
        env.setdefault("CT2_USE_EXPERIMENTAL_PACKED_GEMM", "0")

        print(
            f"[voice-pro asr] starting worker model={params.model_size} "
            f"compute={params.compute_type} input={input_path}",
            flush=True,
        )

        try:
            result = subprocess.run(
                cmd,
                cwd=str(Path(__file__).resolve().parent.parent),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Transcribe timed out after 600 seconds") from exc

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if stdout:
            print(f"[voice-pro asr] worker stdout:\n{stdout}", flush=True)
        if stderr:
            print(f"[voice-pro asr] worker stderr:\n{stderr}", flush=True)

        try:
            with open(output_json, "r", encoding="utf-8") as f:
                payload = json.load(f)
        finally:
            try:
                os.remove(output_json)
            except OSError:
                pass

        if result.returncode != 0 or payload.get("error"):
            raise RuntimeError(payload.get("traceback") or payload.get("error") or stderr or stdout)

        subtitles = payload.get("subtitles") or []
        print(f"[voice-pro asr] worker finished subtitles={len(subtitles)}", flush=True)
        return subtitles
                
    # return inst, vocal    
    def _denoise(self, source_audio, denoise_level=2):
        if denoise_level == 1:
            return self._demucs_htdemucs(source_audio)
        elif denoise_level ==2:
            return self._demucs_htdemucs_ft(source_audio)
        else:
            return "", ""
                
        
            
    def _demucs_htdemucs(self, source_audio):
        _, extension = os.path.splitext(os.path.basename(source_audio))
        output_dir = os.path.dirname(source_audio)
        
        inst_audio_file, vocal_audio_file = demucs_split_file(source_audio, output_dir, 'htdemucs', extension[1:])
        self.fm.set_split("Instrumental.audio", inst_audio_file)
        self.fm.set_split("Vocals.audio", vocal_audio_file)

        return inst_audio_file, vocal_audio_file
    
    def _demucs_htdemucs_ft(self, source_audio):
        _, extension = os.path.splitext(os.path.basename(source_audio))
        output_dir = os.path.dirname(source_audio)
        
        inst_audio_file, vocal_audio_file = demucs_split_file(source_audio, output_dir, 'htdemucs_ft', extension[1:])
        self.fm.set_split("Instrumental.audio", inst_audio_file)
        self.fm.set_split("Vocals.audio", vocal_audio_file)

        return inst_audio_file, vocal_audio_file    
    
    def _read_subtitle_file(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        return content    

        

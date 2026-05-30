import base64
import os
import platform
import gradio as gr
from yt_dlp import YoutubeDL
from yt_dlp.postprocessor import PostProcessor

from app.abus_path import cmd_rename_file, path_shorten

import structlog
logger = structlog.get_logger()


def _youtube_cookiefile(download_folder: str) -> str | None:
    configured_path = os.getenv("YTDLP_COOKIES_PATH") or os.getenv("YOUTUBE_COOKIES_PATH")
    if configured_path and os.path.exists(configured_path):
        return configured_path

    encoded_cookies = os.getenv("YTDLP_COOKIES_B64") or os.getenv("YOUTUBE_COOKIES_B64")
    plain_cookies = os.getenv("YTDLP_COOKIES") or os.getenv("YOUTUBE_COOKIES")
    if encoded_cookies or plain_cookies:
        cookiefile_path = os.path.join(download_folder, "youtube_cookies.txt")
        try:
            if encoded_cookies:
                cookie_content = base64.b64decode(encoded_cookies).decode("utf-8")
            else:
                cookie_content = plain_cookies.replace("\\n", "\n")
            with open(cookiefile_path, "w", encoding="utf-8") as cookie_file:
                cookie_file.write(cookie_content)
            return cookiefile_path
        except Exception as exc:
            logger.error(f"[abus_downloader.py] cookiefile setup failed: {exc}")

    local_cookiefile = os.path.join(os.getcwd(), "cookies.txt")
    if os.path.exists(local_cookiefile):
        return local_cookiefile
    return None


class FilenameCollectorPP(PostProcessor):
    def __init__(self):
        super(FilenameCollectorPP, self).__init__(None)
        self.filenames = []

    def run(self, information):
        self.filenames.append(information["filepath"])
        return [], information
    

class ExceededMaximumDuration(Exception):
    def __init__(self, videoDuration, maxDuration, message):
        self.videoDuration = videoDuration
        self.maxDuration = maxDuration
        super().__init__(message)    
    
    
class YoutubeDownloader:
    def __init__(self):
        self.progress = gr.Progress()         
        
    def validate_path(self, path):
        try:
            shortened_path = path_shorten(path)
            cmd_rename_file(path, shortened_path)
        except ValueError as e:
            shortened_path = path
            logger.error(f"validate_path - Error: {e}")    

        return shortened_path
        
        
    def dl_progress_hook(self, d):
        if "status" not in d:
            return
        
        try:
            total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded_bytes = d.get("downloaded_bytes") or 0
            
            if d["status"] == "downloading" and total_bytes > 0:
                self.progress(int(downloaded_bytes / total_bytes * 100) / 100.0, desc="YouTube Downloader")
            elif d["status"] == "finished":
                self.progress(1.0, desc="YouTube Downloader")
        except Exception as e:
            logger.error(f"[abus_downloader.py] dl_progress_hook - An error occurred: {e}")

   
    def yt_download(self, url: str, download_folder: str, quality: str = "good", maxDuration: int = None):       
        ydl_opts = {}
        ydl_opts['keepvideo'] = False
        ydl_opts['progress_hooks'] = [self.dl_progress_hook]
        ydl_opts['playlist_items'] = '1'
        ydl_opts['check_formats'] = False
        ydl_opts['merge_output_format'] = 'mp4'
        ydl_opts['extractor_args'] = {'youtube': {'player_client': ['web', 'android', 'ios']}}

        bun_path = os.path.expanduser('~/.bun/bin/bun')
        if os.path.exists(bun_path):
            ydl_opts['js_runtimes'] = {'bun': {'path': bun_path}}
        
        # User Agent 설정 추가
        ydl_opts['http_headers'] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9'
        }        
        
        cookiefile_path = _youtube_cookiefile(download_folder)
        if cookiefile_path:
            ydl_opts['cookiefile'] = cookiefile_path
        elif platform.system() == "Linux":
            logger.warning("[abus_downloader.py] no YouTube cookiefile configured; some videos may require sign-in cookies")

        
        if quality == "best":
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best'
        elif quality == "good":
            ydl_opts['format'] = (
                'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/'
                'bestvideo[height<=720]+bestaudio/'
                'best[ext=mp4][height<=720]/best[height<=720]/best[ext=mp4]/best'
            )
        elif quality in ("low", "worst"):
            ydl_opts['format'] = (
                'bestvideo[ext=mp4][height<=360]+bestaudio[ext=m4a]/'
                'bestvideo[height<=360]+bestaudio/'
                'best[ext=mp4][height<=360]/best[height<=360]/worst[ext=mp4]/worst/best'
            )
        else:
            ydl_opts['format'] = 'best[ext=mp4]/best'

        ydl_opts['outtmpl'] = download_folder + '/%(title)s.f%(format_id)s.%(ext)s'

        filename_collector = FilenameCollectorPP()
        with YoutubeDL(ydl_opts) as ydl:
            if maxDuration and maxDuration > 0:
                info = ydl.extract_info(url, download=False)
                entries = "entries" in info and info["entries"] or [info]
                total_duration = 0

                # Compute total duration
                for entry in entries:
                    total_duration += float(entry["duration"])

                if total_duration >= maxDuration:
                    raise ExceededMaximumDuration(videoDuration=total_duration, maxDuration=maxDuration, message="Video is too long")

            ydl.add_post_processor(filename_collector)
            try:
                ydl.download([url])
            except Exception as exc:
                message = str(exc)
                if "Sign in to confirm" in message or "not a bot" in message:
                    raise Exception(
                        "YouTube bot doğrulamasına takıldı. Coolify env içine YTDLP_COOKIES_B64 "
                        "veya YTDLP_COOKIES_PATH eklenmeli. YouTube cookies.txt dosyasını Netscape formatında export edip base64 olarak girin."
                    ) from exc
                if "Requested format is not available" in message:
                    logger.warning("[abus_downloader.py] requested format unavailable; retrying with bestaudio/best")
                    fallback_opts = dict(ydl_opts)
                    fallback_opts["format"] = "bestaudio/best"
                    filename_collector.filenames.clear()
                    with YoutubeDL(fallback_opts) as fallback_ydl:
                        fallback_ydl.add_post_processor(filename_collector)
                        fallback_ydl.download([url])
                    return self.validate_path(filename_collector.filenames[0])
                raise

        if len(filename_collector.filenames) <= 0:
            raise Exception("Cannot download " + url)
        
        
        valid_path = self.validate_path(filename_collector.filenames[0])
        return valid_path
                

                

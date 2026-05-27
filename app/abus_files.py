import os
from app.abus_path import *

import structlog
logger = structlog.get_logger()


class FileManager:
    def __init__(self) -> None:
        self.splits = {}
        self.subtitles = {}
        self.translations = {}
        self.dubbings = {}
        self.covers = {}
        self.effects = {}
    
    # splits
    def get_split(self, key, default=None):
        file_path = self.splits.get(key, default)
        return file_path
    
    def set_split(self, key, file_path):
        self.splits[key] = file_path        
    
    def get_all_splits(self) -> list:
        values_list = [value for value in self.splits.values() if value is not None]
        return values_list
    
    # subtitle
    def get_subtitle(self, key, default=None):
        file_path = self.subtitles.get(key, default)
        return file_path

    def set_subtitle(self, key, file_path):
        self.subtitles[key] = file_path
    
    def set_subtitles(self, subtitles, language: str, audio_path: str = ""):
        self.subtitles = {}

        if not subtitles:
            logger.warning('[abus_files.py] set_subtitles: no subtitle files were generated')
            return
        
        for file_path in subtitles:
            file_name, file_extension = os.path.splitext(os.path.basename(file_path))
            target_path = path_add_postfix(audio_path, f'_{language}', file_extension)
            target_path = cmd_safe_rename(file_path, target_path)
            self.set_subtitle(file_extension.lower(), target_path)                
        
    def get_all_subtitles(self) -> list:
        values_list = [value for value in self.subtitles.values() if value is not None]
        return values_list        
        
    
    # translations
    def get_translation(self, language: str, file_extension: str, default=None):
        logger.debug(f'[abus_files.py] [abus_files.py] get_translation: {language}, {file_extension}')
        
        key = f'{language}{file_extension}'
        file_path = self.translations.get(key.lower(), default)
        return file_path
    
    def set_translation(self, language, file_path):
        file_name, file_extension = os.path.splitext(os.path.basename(file_path))
        key = f'{language}{file_extension}'
        
        logger.debug(f'[abus_files.py] set_translation: {language}, {file_extension}')
        self.translations[key.lower()] = file_path
        
    def get_all_translations(self) -> list:
        values_list = [value for value in self.translations.values() if value is not None]
        return values_list              


    # dubbings
    def get_dubbing(self, key, default=None):
        file_path = self.dubbings.get(key, default)
        return file_path
    
    def set_dubbing(self, key, file_path):
        self.dubbings[key] = file_path        
    
    def get_all_dubbings(self) -> list:
        values_list = [value for value in self.dubbings.values() if value is not None]
        return values_list

    
    # covers
    def get_cover(self, key, default=None):
        file_path = self.covers.get(key, default)
        return file_path
    
    def set_cover(self, key, file_path):
        self.covers[key] = file_path        
    
    def get_all_covers(self) -> list:
        values_list = [value for value in self.covers.values() if value is not None]
        return values_list    


    # effects
    def get_effect(self, key, default=None):
        file_path = self.effects.get(key, default)
        return file_path
    
    def set_effect(self, key, file_path):
        self.effects[key] = file_path        
    
    def get_all_effects(self) -> list:
        values_list = [value for value in self.effects.values() if value is not None]
        return values_list    
        
        
    # all
    def get_all_files(self) -> list:
        files = []
        files.extend(self.get_all_splits())
        files.extend(self.get_all_subtitles())
        files.extend(self.get_all_translations())
        files.extend(self.get_all_dubbings())
        files.extend(self.get_all_covers())
        files.extend(self.get_all_effects())
        
        return files
        
        

    
    
    

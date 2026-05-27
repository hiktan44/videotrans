import gradio as gr
import pysubs2
import re
from deep_translator import GoogleTranslator

from app.abus_genuine import *
from app.abus_path import *
from app.abus_text import *
from app.abus_nlp_spacy import *

import structlog
logger = structlog.get_logger()

class DeepTranslator:
    def __init__(self) -> None:
        self.translator = GoogleTranslator(source='auto', target='en')
        self.languages_dict = GoogleTranslator().get_supported_languages(as_dict=True)
        
   
    def get_languages(self) -> list:
        capitalized_keys = [key.capitalize() for key in self.languages_dict.keys()]
        return capitalized_keys
    
    def get_language_code(self, language_name) -> str:
        search_name = language_name.lower()
        for key, value in self.languages_dict.items():
            if key.lower() == search_name:
                return value
        return "en"
    
    def get_language_value(self, language_name):
        search_name = language_name.lower()
        for key, value in self.languages_dict.items():
            if key.lower() == search_name:
                return key
        return None    
    
  
    
    def translate_text(self, source_lang: str, target_lang: str, text: str, progress=gr.Progress()) -> str:
        source_code = self.get_language_code(source_lang)
        target_code = self.get_language_code(target_lang)
        
        self.translator.source = source_code
        self.translator.target = target_code
        
        # line 끝 마침표 확인인
        use_punctuation = AbusText.has_ending_marks([text])
        
        # 텍스트를 문장 단위로 분리
        sentences = AbusText.split_into_sentences(text, use_punctuation)
        sentences = sentences
        
        translated_sentences = []
        
        # 각 문장을 번역
        for sentence in progress.tqdm(sentences, desc="Translating sentences..."):
            try:
                translated = self.translator.translate(text=sentence)
                translated_sentences.append(translated)
                logger.debug(f"[abus_translate_deep.py] translate_text - {source_code}: {sentence} -> {target_code}: {translated}")
            except Exception as e:
                logger.error(f"Translation error: {e}")
                translated_sentences.append(sentence)  # 에러 발생 시 원본 문장 사용
        
        # 번역된 문장들을 다시 하나의 텍스트로 결합
        final_text = ' '.join(translated_sentences)
        return final_text

    def translate_file(self, source_lang: str, target_lang: str, subtitle_file_path: str, output_file_path: str, progress=gr.Progress()):
        source_code = self.get_language_code(source_lang)
        target_code = self.get_language_code(target_lang)

        
        translator = GoogleTranslator(source=source_code, target=target_code)
        logger.debug(f"[abus_translate_deep.py] translate_file {source_code}: {subtitle_file_path} -> {target_code}: {output_file_path}")

        # Keep the original subtitle timings during translation. TTS-specific
        # splitting is handled later by the TTS engines.
        full_subs = pysubs2.load(subtitle_file_path, encoding="utf-8")
        subs = full_subs
        previous_text = ""
        previous_repeats = 0
        
        for event in progress.tqdm(subs, desc='Translate...'):
            if not event.text:
                continue
                
            text = event.plaintext
            normalized = self._normalize_text(text)
            if normalized == previous_text:
                previous_repeats += 1
                if previous_repeats >= 2:
                    event.text = ""
                    continue
            else:
                previous_repeats = 0
                previous_text = normalized

            try:
                translated_text = translator.translate(text)
                if translated_text:
                    event.text = self._collapse_repeated_phrases(translated_text)
                    logger.debug(f"[abus_translate_deep.py] translate_file : text       - {text}")
                    logger.debug(f"[abus_translate_deep.py] translate_file : translated - {translated_text}")                        
                else:
                    logger.warning(f"[abus_translate_deep.py] translate_file - Empty translation for: {text}")
            except Exception as e:
                logger.error(f"Translation error for text '{text}': {e}")
                # 에러 발생 시 원본 텍스트 유지

        subs.events = [event for event in subs.events if event.text.strip()]
        subs.save(output_file_path)   

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\W+", " ", text.lower()).strip()

    @staticmethod
    def _collapse_repeated_phrases(text: str) -> str:
        words = text.split()
        if len(words) < 3:
            return text

        collapsed = []
        i = 0
        while i < len(words):
            replaced = False
            for phrase_len in range(1, 5):
                if i + phrase_len * 3 > len(words):
                    continue
                phrase = words[i:i + phrase_len]
                repeats = 1
                while words[i + repeats * phrase_len:i + (repeats + 1) * phrase_len] == phrase:
                    repeats += 1
                if repeats >= 3:
                    collapsed.extend(phrase)
                    i += repeats * phrase_len
                    replaced = True
                    break
            if not replaced:
                collapsed.append(words[i])
                i += 1

        return " ".join(collapsed)

            

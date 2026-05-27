from dataclasses import dataclass, fields
import copy

@dataclass
class WhisperParameters:
    model_size: str = 'small'
    lang: str = 'Automatic Detection'
    is_translate: bool = False
    vad_filter: bool = True         # False - default
    beam_size: int = 5              # 5 - default
    log_prob_threshold: float = -1.0    # -1.0 - default
    no_speech_threshold: float = 0.6    # 0.6 - default
    compute_type: str = 'default'   # 'int8_float16', 'float32', 'int8', 'int8_float32', 'float16', 'bfloat16', 'int8_bfloat16'
    best_of: int = 5                # 5 - default
    patience: float = 1.0           # 1 - default
    condition_on_previous_text: bool = False     # True - default
    temperature = 0 # https://github.com/SYSTRAN/faster-whisper/issues/71
    word_timestamps: bool = False                       # False - default    
    hallucination_silence_threshold = 0.5               # None - default
    repetition_penalty = 1.2                            # 1 - default
    vad_parameters = dict(min_silence_duration_ms=500)  # None - default
    denoise_level: int = 0
    initial_prompt: str = 'We use all the standard punctuation and capitalization rules of the English language. Sentences start with a capital letter, and end with a full stop. Of course, where appropriate, commas are included.'
    """
    A data class to use Whisper parameters in your function after Gradio pre-processing.
    See this documentation for more information about Gradio pre-processing: : https://www.gradio.app/docs/components
    """
    
    def copy(self):
        return copy.copy(self)

import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowRight,
  Captions,
  CheckCircle2,
  Download,
  FileAudio,
  Globe2,
  Link2,
  Loader2,
  Mic2,
  PlayCircle,
  Sparkles,
  UploadCloud,
  Video,
  Volume2,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

const LANGUAGE_OPTIONS = [
  "Afrikaans",
  "Albanian",
  "Amharic",
  "Arabic",
  "Armenian",
  "Assamese",
  "Aymara",
  "Azerbaijani",
  "Bambara",
  "Basque",
  "Belarusian",
  "Bengali",
  "Bhojpuri",
  "Bosnian",
  "Bulgarian",
  "Catalan",
  "Cebuano",
  "Chinese",
  "Chinese (Simplified)",
  "Chinese (Traditional)",
  "Corsican",
  "Croatian",
  "Czech",
  "Danish",
  "Dhivehi",
  "Dogri",
  "Dutch",
  "English",
  "Esperanto",
  "Estonian",
  "Ewe",
  "Filipino",
  "Finnish",
  "French",
  "Frisian",
  "Galician",
  "Georgian",
  "German",
  "Greek",
  "Guarani",
  "Gujarati",
  "Haitian Creole",
  "Hausa",
  "Hawaiian",
  "Hebrew",
  "Hindi",
  "Hmong",
  "Hungarian",
  "Icelandic",
  "Igbo",
  "Ilocano",
  "Indonesian",
  "Irish",
  "Italian",
  "Japanese",
  "Javanese",
  "Kannada",
  "Kazakh",
  "Khmer",
  "Kinyarwanda",
  "Konkani",
  "Korean",
  "Krio",
  "Kurdish",
  "Kurdish (Sorani)",
  "Kyrgyz",
  "Lao",
  "Latin",
  "Latvian",
  "Lingala",
  "Lithuanian",
  "Luganda",
  "Luxembourgish",
  "Macedonian",
  "Maithili",
  "Malagasy",
  "Malay",
  "Malayalam",
  "Maltese",
  "Maori",
  "Marathi",
  "Meiteilon",
  "Mizo",
  "Mongolian",
  "Myanmar",
  "Nepali",
  "Norwegian",
  "Nyanja",
  "Odia",
  "Oromo",
  "Pashto",
  "Persian",
  "Polish",
  "Portuguese",
  "Punjabi",
  "Quechua",
  "Romanian",
  "Russian",
  "Samoan",
  "Sanskrit",
  "Scots Gaelic",
  "Serbian",
  "Sesotho",
  "Shona",
  "Sindhi",
  "Sinhala",
  "Slovak",
  "Slovenian",
  "Somali",
  "Spanish",
  "Sundanese",
  "Swahili",
  "Swedish",
  "Tajik",
  "Tamil",
  "Tatar",
  "Telugu",
  "Thai",
  "Tigrinya",
  "Tsonga",
  "Turkish",
  "Turkmen",
  "Twi",
  "Ukrainian",
  "Urdu",
  "Uyghur",
  "Uzbek",
  "Vietnamese",
  "Welsh",
  "Xhosa",
  "Yiddish",
  "Yoruba",
  "Zulu",
];

const SOURCE_LANGUAGE_OPTIONS = ["Automatic Detection", ...LANGUAGE_OPTIONS];
const TARGET_LANGUAGE_OPTIONS = ["Turkish", ...LANGUAGE_OPTIONS.filter((language) => language !== "Turkish")];

type Job = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  message: string;
  outputs: Record<string, string>;
  error?: string | null;
};

type Step = "transcribe" | "translate" | "dubbing" | "exports";
type CaptionMode = "off" | "source" | "translated";
type VoiceGender = "female" | "male";

const landingFeatures = [
  {
    icon: <FileAudio size={20} />,
    title: "Otomatik transkripsiyon",
    text: "Videodaki konuşmaları zaman kodlu altyazıya ve düzenlenebilir metne dönüştür.",
  },
  {
    icon: <Globe2 size={20} />,
    title: "Akıllı çeviri",
    text: "Altyazıları hedef dile çevir, tekrar eden satırları temizle ve lokalize içerik hazırla.",
  },
  {
    icon: <Mic2 size={20} />,
    title: "Doğal dublaj",
    text: "Kadın veya erkek ses seçimiyle hedef dilde senkronize seslendirme üret.",
  },
  {
    icon: <Captions size={20} />,
    title: "Altyazı kontrolü",
    text: "Orijinal, çevrilmiş veya altyazısız oynatma seçeneklerini tek ekrandan yönet.",
  },
];

const landingSteps = [
  "Videonu yükle veya YouTube linkini ekle.",
  "Konuşmaları otomatik olarak altyazıya dönüştür.",
  "Hedef dili seç, çeviriyi oluştur ve düzenle.",
  "Ses seçimini yap, dublajlı videonu indir.",
];

function scrollToStudio() {
  document.getElementById("studio")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function LandingPage() {
  return (
    <section className="landing">
      <header className="landingNav">
        <div className="landingBrand">
          <span>VT</span>
          <strong>VideoTrans</strong>
        </div>
        <div className="landingNavLinks">
          <a href="#features">Özellikler</a>
          <a href="#workflow">Nasıl çalışır?</a>
          <button onClick={scrollToStudio}>Uygulamayı aç</button>
        </div>
      </header>

      <section className="hero">
        <div className="heroCopy">
          <span className="eyebrow">
            <Sparkles size={16} />
            AI video lokalizasyon stüdyosu
          </span>
          <h1>Videolarını dakikalar içinde farklı dillere taşı.</h1>
          <p>
            VideoTrans videonu yazıya döker, çevirir, altyazı oluşturur ve seçtiğin dilde dublajlı çıktı hazırlar.
            YouTube linki veya video dosyasıyla tek akışta global içerik üret.
          </p>
          <div className="heroActions">
            <button className="heroPrimary" onClick={scrollToStudio}>
              Hemen dene
              <ArrowRight size={18} />
            </button>
            <a className="heroSecondary" href="#workflow">
              Nasıl çalışır?
            </a>
          </div>
        </div>

        <div className="heroStage" aria-label="VideoTrans workflow preview">
          <div className="filmFrame">
            <div className="frameTop">
              <span />
              <span />
              <span />
            </div>
            <div className="videoMock">
              <PlayCircle size={54} />
              <div>
                <strong>Global launch video</strong>
                <p>EN to TR altyazı ve dublaj hazırlanıyor</p>
              </div>
            </div>
            <div className="captionLine">"Ürününüzü dünyaya kendi dilinde anlatın."</div>
          </div>
          <div className="metricStrip">
            <div>
              <strong>4 adım</strong>
              <span>yükle, yaz, çevir, dublajla</span>
            </div>
            <div>
              <strong>100+ dil</strong>
              <span>Türkçe varsayılan hedef dil</span>
            </div>
          </div>
        </div>
      </section>

      <section className="landingBand">
        <p>Tek video, çok dil. İçerik üreticileri, eğitimciler, ajanslar ve SaaS ekipleri için hızlı lokalizasyon.</p>
      </section>

      <section id="features" className="featureSection">
        <div className="sectionIntro">
          <span>Özellikler</span>
          <h2>Transcribe, translate, subtitle ve dubbing tek yerde.</h2>
        </div>
        <div className="featureGrid">
          {landingFeatures.map((feature) => (
            <article className="featureCard" key={feature.title}>
              <div>{feature.icon}</div>
              <h3>{feature.title}</h3>
              <p>{feature.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="workflow" className="workflowSection">
        <div className="sectionIntro">
          <span>İş akışı</span>
          <h2>Dağınık araçları tek üretim hattına indir.</h2>
        </div>
        <div className="workflowGrid">
          {landingSteps.map((step, index) => (
            <article className="workflowStep" key={step}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <p>{step}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="audienceSection">
        <div>
          <Video size={22} />
          <strong>İçerik üreticileri</strong>
          <p>YouTube, Instagram, TikTok ve eğitim videolarını yeni pazarlara aç.</p>
        </div>
        <div>
          <Globe2 size={22} />
          <strong>Ajanslar ve ekipler</strong>
          <p>Müşteriler için hızlı altyazı, çeviri ve dublaj çıktıları hazırla.</p>
        </div>
        <div>
          <Download size={22} />
          <strong>Hazır çıktı</strong>
          <p>Altyazı dosyalarını, seslendirmeyi ve dublajlı video çıktısını indir.</p>
        </div>
      </section>

      <section className="finalCta">
        <h2>Videolarını tek dilden çıkar.</h2>
        <p>VideoTrans ile altyazılı, çevrilmiş ve dublajlı içerikleri daha hızlı üret.</p>
        <button className="heroPrimary" onClick={scrollToStudio}>
          VideoTrans'ı dene
          <ArrowRight size={18} />
        </button>
      </section>
    </section>
  );
}

function LoginGate({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submitLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const form = new FormData();
    form.append("password", password);
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      body: form,
      credentials: "include",
    });
    setSubmitting(false);
    if (!response.ok) {
      setError("Şifre hatalı. Lütfen tekrar dene.");
      return;
    }
    setPassword("");
    onLogin();
  }

  return (
    <section id="studio" className="loginGate">
      <div className="loginPanel">
        <span className="eyebrow">
          <Sparkles size={16} />
          Korumalı studio
        </span>
        <h2>Uygulamaya giriş yap</h2>
        <p>Video yükleme, transcribe, translate ve dubbing araçları sadece giriş yapan kullanıcılar için görünür.</p>
        <form onSubmit={submitLogin}>
          <label>
            Şifre
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Studio şifresi"
              autoComplete="current-password"
            />
          </label>
          {error && <strong className="loginError">{error}</strong>}
          <button className="heroPrimary" disabled={!password || submitting}>
            {submitting ? <Loader2 className="spin" size={18} /> : <ArrowRight size={18} />}
            Giriş yap
          </button>
        </form>
      </div>
    </section>
  );
}

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("gpt-4o-transcribe-diarize");
  const [language, setLanguage] = useState("Automatic Detection");
  const [mediaUrl, setMediaUrl] = useState("");
  const [videoQuality, setVideoQuality] = useState("good");
  const [job, setJob] = useState<Job | null>(null);
  const [translateJob, setTranslateJob] = useState<Job | null>(null);
  const [activeStep, setActiveStep] = useState<Step>("transcribe");
  const [subtitleText, setSubtitleText] = useState("");
  const [translatedText, setTranslatedText] = useState("");
  const [translateProvider, setTranslateProvider] = useState("auto");
  const [sourceLanguage, setSourceLanguage] = useState("Automatic Detection");
  const [targetLanguage, setTargetLanguage] = useState("Turkish");
  const [captionMode, setCaptionMode] = useState<CaptionMode>("off");
  const [dubbingJob, setDubbingJob] = useState<Job | null>(null);
  const [dubbingProvider, setDubbingProvider] = useState("edge");
  const [dubbingVoice, setDubbingVoice] = useState("tr-TR-EmelNeural");
  const [voiceGender, setVoiceGender] = useState<VoiceGender>("female");
  const [dubbingSpeed, setDubbingSpeed] = useState(0.82);
  const [dubbing, setDubbing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);

  const canSubmit = useMemo(() => Boolean((file || mediaUrl.trim()) && !busy), [file, mediaUrl, busy]);
  const sourceCaptionHref = job?.outputs?.vtt;
  const translatedCaptionHref = translateJob?.outputs?.vtt;
  const activeCaptionHref =
    captionMode === "translated" ? translatedCaptionHref : captionMode === "source" ? sourceCaptionHref : undefined;

  useEffect(() => {
    refreshAuth();
  }, []);

  async function refreshAuth() {
    const response = await fetch(`${API_BASE}/api/auth/session`, { credentials: "include" });
    const session = await response.json();
    setAuthEnabled(Boolean(session.enabled));
    setAuthenticated(Boolean(session.authenticated));
    setAuthChecked(true);
  }

  async function startTranscribe() {
    if (!file && !mediaUrl.trim()) return;
    setBusy(true);
    const form = new FormData();
    if (file) {
      form.append("file", file);
    }
    form.append("youtube_url", mediaUrl.trim());
    form.append("video_quality", videoQuality);
    form.append("provider", provider);
    form.append("model", model);
    form.append("language", language);
    form.append("audio_format", "mp3");

    const response = await fetch(`${API_BASE}/api/jobs/transcribe`, {
      method: "POST",
      body: form,
      credentials: "include",
    });
    if (!response.ok) {
      setBusy(false);
      throw new Error(await response.text());
    }
    const created = (await response.json()) as Job;
    setJob(created);
    pollJob(created.id);
  }

  async function pollJob(jobId: string) {
    const timer = window.setInterval(async () => {
      const response = await fetch(`${API_BASE}/api/jobs/${jobId}`);
      const current = (await response.json()) as Job;
      setJob(current);
      if (current.status === "completed" || current.status === "failed") {
        window.clearInterval(timer);
        setBusy(false);
        if (current.status === "completed") {
          hydrateCompletedJob(current);
        }
      }
    }, 1500);
  }

  async function hydrateCompletedJob(doneJob: Job) {
    const srtHref = doneJob.outputs?.srt;
    if (srtHref) {
      const response = await fetch(`${API_BASE}${srtHref}`);
      setSubtitleText(await response.text());
    }
    setActiveStep("translate");
  }

  async function startTranslate() {
    if (!subtitleText.trim()) return;
    setTranslating(true);
    const form = new FormData();
    form.append("source_text", subtitleText);
    form.append("source_language", sourceLanguage);
    form.append("target_language", targetLanguage);
    form.append("provider", translateProvider);

    const response = await fetch(`${API_BASE}/api/jobs/translate`, {
      method: "POST",
      body: form,
      credentials: "include",
    });
    if (!response.ok) {
      setTranslating(false);
      throw new Error(await response.text());
    }
    const created = (await response.json()) as Job;
    setTranslateJob(created);
    pollTranslateJob(created.id);
  }

  async function pollTranslateJob(jobId: string) {
    const timer = window.setInterval(async () => {
      const response = await fetch(`${API_BASE}/api/jobs/${jobId}`);
      const current = (await response.json()) as Job;
      setTranslateJob(current);
      if (current.status === "completed" || current.status === "failed") {
        window.clearInterval(timer);
        setTranslating(false);
        if (current.status === "completed" && current.outputs?.srt) {
          const translatedResponse = await fetch(`${API_BASE}${current.outputs.srt}`);
          const nextTranslatedText = await translatedResponse.text();
          setTranslatedText(nextTranslatedText);
          setCaptionMode(current.outputs?.vtt ? "translated" : "off");
          setActiveStep("dubbing");
        }
      }
    }, 1500);
  }

  async function startDubbing(scriptText = translatedText) {
    if (!scriptText.trim() || dubbing) return;
    setDubbing(true);
    setActiveStep("dubbing");
    const form = new FormData();
    form.append("subtitle_text", scriptText);
    form.append("media_job_id", job?.id ?? "");
    form.append("media_href", job?.outputs?.media ?? "");
    form.append("provider", dubbingProvider);
    form.append("voice_name", dubbingVoice);
    form.append("speed", String(dubbingSpeed));
    form.append("audio_format", "mp3");

    const response = await fetch(`${API_BASE}/api/jobs/dubbing`, {
      method: "POST",
      body: form,
      credentials: "include",
    });
    if (!response.ok) {
      setDubbing(false);
      throw new Error(await response.text());
    }
    const created = (await response.json()) as Job;
    setDubbingJob(created);
    pollDubbingJob(created.id);
  }

  async function pollDubbingJob(jobId: string) {
    const timer = window.setInterval(async () => {
      const response = await fetch(`${API_BASE}/api/jobs/${jobId}`);
      const current = (await response.json()) as Job;
      setDubbingJob(current);
      if (current.status === "completed" || current.status === "failed") {
        window.clearInterval(timer);
        setDubbing(false);
        if (current.status === "completed") {
          setActiveStep("exports");
        }
      }
    }, 1500);
  }

  function go(step: Step) {
    if (step === "translate" && !job?.outputs?.srt) return;
    if ((step === "dubbing" || step === "exports") && !translatedText.trim()) return;
    setActiveStep(step);
  }

  return (
    <>
    <LandingPage />
    {authChecked && authEnabled && !authenticated ? (
      <LoginGate onLogin={() => setAuthenticated(true)} />
    ) : (
    <main id="studio" className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">VP</div>
          <div>
            <strong>Voice-Pro Studio</strong>
            <span>Job based dubbing pipeline</span>
          </div>
        </div>

        <nav>
          <button className={`navItem ${activeStep === "transcribe" ? "active" : ""}`} onClick={() => go("transcribe")}>Transcribe</button>
          <button className={`navItem ${activeStep === "translate" ? "active" : ""}`} disabled={!job?.outputs?.srt} onClick={() => go("translate")}>Translate</button>
          <button className={`navItem ${activeStep === "dubbing" ? "active" : ""}`} disabled={!translatedText.trim()} onClick={() => go("dubbing")}>Dubbing</button>
          <button className={`navItem ${activeStep === "exports" ? "active" : ""}`} disabled={!translatedText.trim()} onClick={() => go("exports")}>Exports</button>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{activeStep === "transcribe" ? "Transcribe workspace" : activeStep === "translate" ? "Translate subtitles" : activeStep === "dubbing" ? "Dubbing setup" : "Export files"}</h1>
            <p>{activeStep === "transcribe" ? "Upload media, run transcription, then continue with translation." : activeStep === "translate" ? "Review source subtitles and prepare the translated caption track." : activeStep === "dubbing" ? "Voice generation and video rendering will be wired here next." : "Download generated assets from this job."}</p>
          </div>
          <div className="statusPill">API {API_BASE || "same-origin"}</div>
        </header>

        {activeStep === "transcribe" && <section className="panel">
          <label className="dropzone">
            <UploadCloud size={34} />
            <strong>{file ? file.name : "Drop or choose audio/video"}</strong>
            <span>MP4, MOV, MP3, WAV, M4A, WEBM</span>
            <input
              type="file"
              accept="audio/*,video/*"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>

          <section className="youtubeBox" aria-label="YouTube link upload">
            <div className="youtubeHeader">
              <div className="linkIcon">
                <Link2 size={18} />
              </div>
              <div>
                <strong>YouTube URL ile yükle</strong>
                <span>Dosya seçmeden direkt video linkiyle transcribe başlat.</span>
              </div>
            </div>

            <div className="youtubeControls">
              <label>
                YouTube URL
                <input
                  type="url"
                  placeholder="https://www.youtube.com/watch?v=..."
                  value={mediaUrl}
                  onChange={(event) => setMediaUrl(event.target.value)}
                />
              </label>
              <label>
                Video quality
                <select value={videoQuality} onChange={(event) => setVideoQuality(event.target.value)}>
                  <option value="low">low</option>
                  <option value="good">good</option>
                  <option value="best">best</option>
                </select>
              </label>
            </div>
          </section>

          <div className="controls">
            <label>
              Provider
              <select
                value={provider}
                onChange={(event) => {
                  const nextProvider = event.target.value;
                  setProvider(nextProvider);
                  setModel(nextProvider === "zai" ? "glm-asr-2512" : "gpt-4o-transcribe-diarize");
                }}
              >
                <option value="openai">OpenAI</option>
                <option value="zai">Z.AI</option>
              </select>
            </label>

            <label>
              Model
              <select value={model} onChange={(event) => setModel(event.target.value)}>
                {provider === "zai" ? (
                  <option value="glm-asr-2512">glm-asr-2512</option>
                ) : (
                  <>
                    <option value="gpt-4o-transcribe-diarize">gpt-4o-transcribe-diarize</option>
                    <option value="gpt-4o-transcribe">gpt-4o-transcribe</option>
                    <option value="gpt-4o-mini-transcribe">gpt-4o-mini-transcribe</option>
                    <option value="whisper-1">whisper-1</option>
                  </>
                )}
              </select>
            </label>

            <label>
              Language
              <select value={language} onChange={(event) => setLanguage(event.target.value)}>
                {SOURCE_LANGUAGE_OPTIONS.map((option) => (
                  <option key={option}>{option}</option>
                ))}
              </select>
            </label>

            <button className="primary" disabled={!canSubmit} onClick={startTranscribe}>
              {busy ? <Loader2 className="spin" size={18} /> : <FileAudio size={18} />}
              Start transcribe
            </button>
          </div>
        </section>}

        {job && (
          <section className="jobPanel">
            <div className="jobHeader">
              <div>
                <span className={`dot ${job.status}`} />
                <strong>{job.status}</strong>
                <small>{job.id}</small>
              </div>
              <span>{Math.round((job.progress ?? 0) * 100)}%</span>
            </div>
            <div className="progress">
              <div style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }} />
            </div>
            <p>{job.error ?? job.message}</p>

            {job.status === "completed" && (
              <div className="outputs">
                <CheckCircle2 size={18} />
                {Object.entries(job.outputs).filter(([kind, href]) => kind !== "media" && kind !== "audio" && href.startsWith("/api/")).map(([kind, href]) => (
                  <a key={kind} href={`${API_BASE}${href}`} target="_blank" rel="noreferrer">
                    Download {kind.toUpperCase()}
                  </a>
                ))}
              </div>
            )}
          </section>
        )}

        {job?.outputs?.media && (
          <section className="previewPanel">
            <div className="previewHeader">
              <div>
                <h2>Video preview</h2>
                <p>Çevrilen altyazı hazır olduğunda videoya otomatik eklenir.</p>
              </div>
              <label>
                Subtitle
                <select value={captionMode} onChange={(event) => setCaptionMode(event.target.value as CaptionMode)}>
                  <option value="off">No subtitles</option>
                  <option value="source" disabled={!sourceCaptionHref}>Original</option>
                  <option value="translated" disabled={!translatedCaptionHref}>Translated</option>
                </select>
              </label>
            </div>
            <video key={`${job.outputs.media}-${captionMode}-${activeCaptionHref ?? "off"}`} src={`${API_BASE}${job.outputs.media}`} controls>
              {activeCaptionHref && (
                <track
                  key={activeCaptionHref}
                  kind="subtitles"
                  src={`${API_BASE}${activeCaptionHref}`}
                  srcLang={captionMode === "translated" ? targetLanguage.slice(0, 2).toLowerCase() : "source"}
                  label={captionMode === "translated" ? `Translated (${targetLanguage})` : "Original"}
                  default
                />
              )}
            </video>
          </section>
        )}

        {activeStep === "translate" && (
          <>
            <section className="translateToolbar">
              <label>
                Provider
                <select value={translateProvider} onChange={(event) => setTranslateProvider(event.target.value)}>
                  <option value="auto">Auto fallback</option>
                  <option value="zai">Z.AI</option>
                  <option value="deep">Deep Translator</option>
                  <option value="azure">Azure</option>
                </select>
              </label>
              <label>
                Source
                <select value={sourceLanguage} onChange={(event) => setSourceLanguage(event.target.value)}>
                  {SOURCE_LANGUAGE_OPTIONS.map((option) => (
                    <option key={option}>{option}</option>
                  ))}
                </select>
              </label>
              <label>
                Target
                <select value={targetLanguage} onChange={(event) => setTargetLanguage(event.target.value)}>
                  {TARGET_LANGUAGE_OPTIONS.map((option) => (
                    <option key={option}>{option}</option>
                  ))}
                </select>
              </label>
              <button className="primary" disabled={!subtitleText.trim() || translating} onClick={startTranslate}>
                {translating ? <Loader2 className="spin" size={18} /> : <FileAudio size={18} />}
                Start translate
              </button>
            </section>

            {translateJob && (
              <section className="jobPanel compact">
                <div className="jobHeader">
                  <div>
                    <span className={`dot ${translateJob.status}`} />
                    <strong>translate {translateJob.status}</strong>
                    <small>{translateJob.id}</small>
                  </div>
                  <span>{Math.round((translateJob.progress ?? 0) * 100)}%</span>
                </div>
                <div className="progress">
                  <div style={{ width: `${Math.round((translateJob.progress ?? 0) * 100)}%` }} />
                </div>
                <p>{translateJob.error ?? translateJob.message}</p>
              </section>
            )}

            <section className="editorGrid">
              <label>
                Source subtitles
                <textarea value={subtitleText} onChange={(event) => setSubtitleText(event.target.value)} />
              </label>
              <label>
                Translated subtitles
                <textarea
                  value={translatedText}
                  placeholder="Start translate ile otomatik dolacak; istersen manuel de düzenleyebilirsin."
                  onChange={(event) => setTranslatedText(event.target.value)}
                />
              </label>
            </section>
          </>
        )}

        {activeStep === "dubbing" && (
          <>
            <section className="panel">
              <h2>Dubbing setup</h2>
              <p className="mutedText">Türkçe altyazıdan zamanlamalı ses üretilir; video varsa yeni sesle MP4 çıktısı hazırlanır.</p>
              <div className="dubbingControls">
                <label>
                  Provider
                  <select
                    value={dubbingProvider}
                    onChange={(event) => {
                      const nextProvider = event.target.value;
                      setDubbingProvider(nextProvider);
                      setDubbingVoice(nextProvider === "openai" ? "marin" : voiceGender === "female" ? "tr-TR-EmelNeural" : "tr-TR-AhmetNeural");
                    }}
                  >
                    <option value="edge">Edge Turkish TTS</option>
                    <option value="openai">OpenAI TTS</option>
                  </select>
                </label>
                <label>
                  Gender
                  <select
                    value={voiceGender}
                    onChange={(event) => {
                      const nextGender = event.target.value as VoiceGender;
                      setVoiceGender(nextGender);
                      if (dubbingProvider === "edge") {
                        setDubbingVoice(nextGender === "female" ? "tr-TR-EmelNeural" : "tr-TR-AhmetNeural");
                      } else {
                        setDubbingVoice(nextGender === "female" ? "marin" : "onyx");
                      }
                    }}
                  >
                    <option value="female">Kadın</option>
                    <option value="male">Erkek</option>
                  </select>
                </label>
                <label>
                  Voice
                  <select value={dubbingVoice} onChange={(event) => setDubbingVoice(event.target.value)}>
                    {dubbingProvider === "openai" ? (
                      <>
                        <option value="marin">marin</option>
                        <option value="cedar">cedar</option>
                        <option value="coral">coral</option>
                        <option value="alloy">alloy</option>
                        <option value="nova">nova</option>
                        <option value="onyx">onyx</option>
                      </>
                    ) : (
                      <>
                        <option value="tr-TR-EmelNeural">tr-TR-EmelNeural</option>
                        <option value="tr-TR-AhmetNeural">tr-TR-AhmetNeural</option>
                      </>
                    )}
                  </select>
                </label>
                <label>
                  Speed: {dubbingSpeed.toFixed(2)}x
                  <input
                    type="range"
                    min="0.65"
                    max="1.15"
                    step="0.05"
                    value={dubbingSpeed}
                    onChange={(event) => setDubbingSpeed(Number(event.target.value))}
                  />
                </label>
                <button className="primary" disabled={!translatedText.trim() || dubbing} onClick={() => startDubbing()}>
                  {dubbing ? <Loader2 className="spin" size={18} /> : <Volume2 size={18} />}
                  Start dubbing
                </button>
              </div>
              <div className="dubbingSummary">
                <span>Subtitle track</span>
                <strong>{translatedCaptionHref ? `Translated (${targetLanguage})` : "Bekleniyor"}</strong>
              </div>
            </section>

            {dubbingJob && (
              <section className="jobPanel compact">
                <div className="jobHeader">
                  <div>
                    <span className={`dot ${dubbingJob.status}`} />
                    <strong>dubbing {dubbingJob.status}</strong>
                    <small>{dubbingJob.id}</small>
                  </div>
                  <span>{Math.round((dubbingJob.progress ?? 0) * 100)}%</span>
                </div>
                <div className="progress">
                  <div style={{ width: `${Math.round((dubbingJob.progress ?? 0) * 100)}%` }} />
                </div>
                <p>{dubbingJob.error ?? dubbingJob.message}</p>
                {dubbingJob.outputs?.audio && (
                  <audio className="audioPreview" src={`${API_BASE}${dubbingJob.outputs.audio}`} controls />
                )}
                {dubbingJob.outputs?.video && (
                  <video className="dubbedVideo" src={`${API_BASE}${dubbingJob.outputs.video}`} controls />
                )}
              </section>
            )}
          </>
        )}

        {activeStep === "exports" && (
          <section className="panel">
            <h2>Exports</h2>
            <div className="outputs exportList">
              {job?.outputs && Object.entries(job.outputs).filter(([, href]) => href.startsWith("/api/")).map(([kind, href]) => (
                <a key={kind} href={`${API_BASE}${href}`} target="_blank" rel="noreferrer">
                  Download {kind.toUpperCase()}
                </a>
              ))}
              {translateJob?.outputs && Object.entries(translateJob.outputs).filter(([, href]) => href.startsWith("/api/")).map(([kind, href]) => (
                <a key={`translate-${kind}`} href={`${API_BASE}${href}`} target="_blank" rel="noreferrer">
                  Download TRANSLATED {kind.toUpperCase()}
                </a>
              ))}
              {dubbingJob?.outputs && Object.entries(dubbingJob.outputs).filter(([, href]) => href.startsWith("/api/")).map(([kind, href]) => (
                <a key={`dubbing-${kind}`} href={`${API_BASE}${href}`} target="_blank" rel="noreferrer">
                  Download DUBBED {kind.toUpperCase()}
                </a>
              ))}
            </div>
          </section>
        )}
      </section>
    </main>
    )}
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);

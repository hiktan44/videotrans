# VideoTrans Coolify Deploy

## App

- Repository: `videotrans`
- Build pack: Dockerfile
- Exposed port: `8787`
- Domain: `https://videotrans.app`

## Required environment variables

Set these in Coolify under Environment Variables:

```env
OPENAI_API_KEY=
OPENAI_TRANSLATE_MODEL=gpt-5-mini
OPENAI_TTS_MODEL=gpt-4o-mini-tts
ZAI_API_KEY=
```

Azure is optional:

```env
AZURE_TRANSLATOR_KEY=
AZURE_TRANSLATOR_ENDPOINT=
AZURE_TRANSLATOR_REGION=
```

## Notes

- The Docker image serves both the React frontend and FastAPI backend from one container.
- Uploaded and generated files are stored under `/app/workspace`.
- Add a persistent volume for `/app/workspace` if job outputs should survive redeploys.

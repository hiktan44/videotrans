import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "studio_api.main:app",
        host="0.0.0.0",
        port=8787,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )

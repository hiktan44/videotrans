FROM node:22-alpine
WORKDIR /app
COPY --chown=node:node package.json server.mjs counter.mjs ./
COPY --chown=node:node public ./public
RUN mkdir -p /var/lib/site-sayaci/private /var/lib/site-sayaci/out && chown -R node:node /var/lib/site-sayaci && chmod 700 /var/lib/site-sayaci/private && chmod 750 /var/lib/site-sayaci/out
USER node
EXPOSE 3806
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q --spider http://127.0.0.1:3806/health || exit 1
CMD ["node","server.mjs"]

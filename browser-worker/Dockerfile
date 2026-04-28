FROM mcr.microsoft.com/playwright:v1.49.0-jammy

WORKDIR /app

COPY package.json /app/

RUN npm install --omit=dev

COPY src /app/src

ENV PORT=7000

EXPOSE 7000

CMD ["node", "src/index.js"]

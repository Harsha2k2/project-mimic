FROM rust:1.79-slim AS builder

WORKDIR /app

COPY Cargo.toml Cargo.lock ./
COPY src ./src

RUN cargo build --release --bin mimetic-sidecar

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/mimetic-sidecar /usr/local/bin/mimetic-sidecar

ENV SIDECAR_PORT=7200

EXPOSE 7200

CMD ["/usr/local/bin/mimetic-sidecar"]

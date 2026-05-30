FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget perl python3 python-is-python3 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── TeX Live (upstream installer, scheme-small) ──────────────────────────────
RUN wget -qO- https://mirror.ctan.org/systems/texlive/tlnet/install-tl-unx.tar.gz \
      | tar -xzC /tmp \
    && TLDIR=$(find /tmp -maxdepth 1 -name 'install-tl-*' -type d | head -1) \
    && printf '%s\n' \
         'selected_scheme scheme-small' \
         'tlpdbopt_autobackup 0' \
         'tlpdbopt_install_docfiles 0' \
         'tlpdbopt_install_srcfiles 0' \
       > /tmp/tl.profile \
    && perl "$TLDIR/install-tl" --profile /tmp/tl.profile \
    && rm -rf /tmp/install-tl* /tmp/tl.profile

# Stable PATH symlink — survives TeX Live year bumps
RUN BINDIR=$(find /usr/local/texlive -name pdflatex | head -1 | xargs -r dirname) \
    && test -n "$BINDIR" \
    && ln -s "$BINDIR" /usr/local/texlive/active-bin
ENV PATH="/usr/local/texlive/active-bin:$PATH"

# texliveonfly installs any missing package automatically on first compile
RUN tlmgr install texliveonfly

# ── uv + Python ──────────────────────────────────────────────────────────────
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /cv

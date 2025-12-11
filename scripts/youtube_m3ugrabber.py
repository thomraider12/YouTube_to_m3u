#!/usr/bin/env python3
# coding: utf-8
"""
youtube_to_m3u.py
Gera uma playlist M3U a partir de um ficheiro de entrada com linhas
do tipo:
- "Nome | Grupo | logo.png | id"
- ou URLs (ex.: https://www.youtube.com/watch?v=XXXXX)

Lê cookies do YouTube a partir da variável de ambiente YT_COOKIES (se existir)
e usa-os com yt-dlp para evitar bloqueios em runners (GitHub Actions).
"""

from __future__ import annotations
import os
import sys
import argparse
import logging
import tempfile
import stat
import json
from typing import Optional

try:
    from yt_dlp import YoutubeDL
except Exception as e:
    print("Erro: yt-dlp não encontrado. Executa: pip install yt-dlp", file=sys.stderr)
    raise

BANNER = r'''
#########################################################################
#      ____            _           _   __  __                           #
#     |  _ \ _ __ ___ (_) ___  ___| |_|  \/  | ___   ___  ___  ___      #
#     | |_) | '__/ _ \| |/ _ \/ __| __| |\/| |/ _ \ / _ \/ __|/ _ \     #
#     |  __/| | | (_) | |  __/ (__| |_| |  | | (_) | (_) \__ \  __/     #
#     |_|   |_|  \___// |\___|\___|\__|_|  |_|\___/ \___/|___/\___|     #
#                   |__/                                                #
#                                  >> https://github.com/benmoose39     #
#########################################################################
'''

FALLBACK_M3U = "https://raw.githubusercontent.com/benmoose39/YouTube_to_m3u/main/assets/moose_na.m3u"

def write_temp_cookies(cookies_text: str) -> Optional[str]:
    """
    Cria um ficheiro temporário com cookies e devolve o path.
    O ficheiro fica com permissões 600.
    """
    if not cookies_text:
        return None
    # Usamos NamedTemporaryFile delete=False para permitir que yt-dlp abra o ficheiro
    tf = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
    try:
        tf.write(cookies_text)
        tf.flush()
        tf.close()
        # garantir permissões 0o600
        try:
            os.chmod(tf.name, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
        return tf.name
    except Exception:
        try:
            tf.close()
            os.unlink(tf.name)
        except Exception:
            pass
        return None

def remove_file_silent(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except Exception:
        pass

def extract_stream_with_yt_dlp(url: str, cookiefile: Optional[str] = None, timeout: int = 15) -> str:
    """
    Usa yt-dlp para extrair formatos e tenta devolver uma URL que contenha .m3u8.
    Se não encontrar, devolve o melhor formato/url disponível.
    Em último caso devolve FALLBACK_M3U.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "dump_single_json": True,
        "format": "best[ext=m3u8]",
        "socket_timeout": timeout,
    }

    if cookiefile:
        # opção correcta para passar ficheiro de cookies
        ydl_opts["cookiefile"] = cookiefile

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logging.debug("yt-dlp falhou para %s : %s", url, e)
        return FALLBACK_M3U

    # procura por .m3u8 nos formatos
    formats = info.get("formats") or []
    for f in formats:
        u = f.get("url") or ""
        if ".m3u8" in u:
            return u

    # procurar em 'requested_formats' ou outros campos
    # (por segurança, verificar info.get('url') e outros)
    if info.get("url") and ".m3u8" in info.get("url"):
        return info.get("url")

    # se não houver .m3u8, tenta devolver o melhor formato 'url' ou fallback
    # preferir 'formats' com 'ext' ou 'format_id' que pareçam video
    if formats:
        # tentar escolher um formato útil (por exemplo o último)
        last = formats[-1].get("url")
        if last:
            return last

    if "url" in info:
        return info["url"]

    return FALLBACK_M3U

def process_file(infile: str, outfile, cookiefile: Optional[str]) -> None:
    """
    Lê o ficheiro de input e escreve M3U para outfile (objeto file-like).
    """
    if not os.path.exists(infile):
        raise FileNotFoundError(infile)

    with open(infile, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.rstrip("\n") for ln in f]

    # cabeçalho M3U
    outfile.write('#EXTM3U x-tvg-url="https://github.com/botallen/epg/releases/download/latest/epg.xml"\n')
    outfile.write(BANNER + "\n")

    for line in lines:
        line = line.strip()
        if not line or line.startswith("~~"):
            continue

        # se linha contiver pipes assume-se metadata
        if "|" in line and not line.lower().startswith("http"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                ch_name = parts[0]
                grp_title = parts[1].title()
                tvg_logo = parts[2]
                tvg_id = parts[3]
                outfile.write(f'\n#EXTINF:-1 group-title="{grp_title}" tvg-logo="{tvg_logo}" tvg-id="{tvg_id}", {ch_name}\n')
                continue
            else:
                # imprime como comentário se formato inesperado
                outfile.write(f'\n# {line}\n')
                continue

        # se começa por http -> é URL
        if line.lower().startswith("http"):
            stream = extract_stream_with_yt_dlp(line, cookiefile=cookiefile)
            outfile.write(stream + "\n")
        else:
            # caso não seja URL nem metadata, ignora
            continue

    outfile.flush()

def main(argv=None):
    parser = argparse.ArgumentParser(description="Gerar M3U a partir de youtube_channel_info.txt (usa yt-dlp).")
    parser.add_argument("-i", "--input", default="../youtube_channel_info.txt", help="Ficheiro de input (default ../youtube_channel_info.txt)")
    parser.add_argument("-o", "--output", default=None, help="Ficheiro de output (se omitido escreve para stdout)")
    parser.add_argument("--timeout", type=int, default=15, help="Timeout interno para yt-dlp (segundos)")
    parser.add_argument("--debug", action="store_true", help="Ativa logging debug")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="[%(levelname)s] %(message)s")

    # ler cookies da variável de ambiente (preenchida pelo workflow)
    cookies_text = os.environ.get("YT_COOKIES", "") or os.environ.get("YOUTUBE_COOKIES", "")
    cookiefile_path = None
    try:
        if cookies_text:
            cookiefile_path = write_temp_cookies(cookies_text)
            logging.debug("Ficheiro de cookies temporário criado: %s", cookiefile_path)
        else:
            logging.debug("Nenhuma variável de cookies encontrada. Prossegue sem cookies.")

        # abre output
        if args.output:
            out_dir = os.path.dirname(os.path.abspath(args.output))
            if out_dir and not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as out_f:
                process_file(args.input, out_f, cookiefile_path)
            logging.info("Ficheiro gerado: %s", args.output)
        else:
            process_file(args.input, sys.stdout, cookiefile_path)

    finally:
        # apaga o ficheiro temporário dos cookies (se criado)
        if cookiefile_path:
            remove_file_silent(cookiefile_path)
            logging.debug("Ficheiro de cookies temporário removido.")

if __name__ == "__main__":
    main()

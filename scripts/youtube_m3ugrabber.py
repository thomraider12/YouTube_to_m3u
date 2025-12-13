#!/usr/bin/env python3
# coding: utf-8
"""
youtube_to_m3u_best.py
Gera uma playlist M3U a partir de um ficheiro de entrada, escolhendo a melhor qualidade disponível.
- Prioriza formatos HLS (.m3u8) na maior resolução possível.
- Se não houver HLS na resolução desejada, devolve o melhor formato disponível (DASH/MP4).
- Suporta cookies passados pela variável de ambiente YT_COOKIES (usado no GitHub Actions).

Uso:
  python3 youtube_to_m3u_best.py -i ../youtube_channel_info.txt -o canais.m3u

"""
from __future__ import annotations
import os
import sys
import argparse
import logging
import tempfile
import stat
from typing import Optional, Dict, Any, List

try:
    from yt_dlp import YoutubeDL
except Exception:
    print("Erro: yt-dlp não instalado. Faz: pip install yt-dlp", file=sys.stderr)
    raise

BANNER = r'''
#########################################################################
#      ____            _           _   __  __                           #
#     |  _ \ _ __ ___ (_) ___  ___| |_|  \/  | ___   ___  ___  ___      #
#     | |_) | '__/ _ \| |/ _ \/ __| __| |\/| |/ _ \ / _ \/ __|/ _ \     #
#     |  __/| | | (_) | |  __/ (__| |_|  |  | | (_) | (_) \__ \  __/     #
#     |_|   |_|  \___// |\___|\___|\__|_|  |_|\___/ \___/|___/\___|     #
#                   |__/                                                #
#                                  >> https://github.com/benmoose39     #
#########################################################################
'''

FALLBACK_M3U = "https://raw.githubusercontent.com/benmoose39/YouTube_to_m3u/main/assets/moose_na.m3u"


def write_temp_cookies(cookies_text: str) -> Optional[str]:
    if not cookies_text:
        return None
    tf = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
    try:
        tf.write(cookies_text)
        tf.flush()
        tf.close()
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


def parse_height(fmt: Dict[str, Any]) -> int:
    """
    Tenta extrair a altura (height) do format dict.
    Retorna 0 se não for possível determinar.
    """
    h = fmt.get("height")
    if isinstance(h, int):
        return h or 0

    # algumas entradas têm 'resolution' como "1280x720" ou "720p"
    res = fmt.get("resolution") or fmt.get("format_note") or fmt.get("format") or ""
    if isinstance(res, str):
        # procurar por '1280x720'
        import re
        m = re.search(r'(\d{2,4})x(\d{2,4})', res)
        if m:
            try:
                return int(m.group(2))
            except Exception:
                pass
        # procurar por '720p'
        m2 = re.search(r'(\d{2,4})p', res)
        if m2:
            try:
                return int(m2.group(1))
            except Exception:
                pass
    return 0


def is_hls_format(fmt: Dict[str, Any]) -> bool:
    """
    Detecta se o format parece HLS (.m3u8).
    """
    proto = (fmt.get("protocol") or "").lower()
    ext = (fmt.get("ext") or "").lower()
    url = (fmt.get("url") or "").lower()
    if "m3u8" in proto or ext == "m3u8" or ".m3u8" in url:
        return True
    # alguns protocolos indicam 'm3u8_native' ou 'hls_manifest'
    if "m3u8" in proto or "hls" in proto:
        return True
    return False


def choose_best_stream_url(info: Dict[str, Any]) -> str:
    """
    A partir do info dict do yt-dlp escolhe a melhor URL:
    1) procura HLS (.m3u8) disponível na maior resolução (height) possível;
    2) se não houver HLS, escolhe o formato com maior resolução (height) e devolve a sua URL;
    3) se nada, devolve fallback.
    """
    formats: List[Dict[str, Any]] = info.get("formats") or []
    if not formats:
        # tentar fallback direto
        if "url" in info and info.get("url"):
            return info.get("url")
        return FALLBACK_M3U

    # construir listas de (height, fmt) ordenadas desc
    entries = []
    for f in formats:
        height = parse_height(f)
        entries.append((height, f))
    entries.sort(key=lambda x: x[0], reverse=True)

    # 1) procurar HLS com maior height
    best_hls = None
    best_hls_height = -1
    for height, f in entries:
        if is_hls_format(f):
            # garantia que tem URL
            url = f.get("url")
            if url:
                best_hls = url
                best_hls_height = height
                break  # entries já ordenados desc -> primeiro é o melhor HLS

    if best_hls:
        logging.debug("Escolhido HLS (melhor disponível): %sp -> %s", best_hls_height, best_hls)
        return best_hls

    # 2) se não houver HLS, escolher melhor formato (maior height) que tenha URL
    for height, f in entries:
        url = f.get("url")
        if url:
            logging.debug("Nenhum HLS encontrado; escolhido melhor formato: %sp -> %s", height, url)
            return url

    # 3) fallback
    if "url" in info and info.get("url"):
        return info.get("url")
    return FALLBACK_M3U


def extract_stream_with_yt_dlp(url: str, cookiefile: Optional[str] = None, timeout: int = 15) -> str:
    """
    Extrai info com yt-dlp e usa choose_best_stream_url para devolver a melhor URL disponível.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "dump_single_json": True,
        "socket_timeout": timeout,
        # não forçar formato aqui — queremos listar todos os formatos e escolher
        # "format": "bestvideo+bestaudio/best",
    }
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logging.debug("yt-dlp falhou para %s : %s", url, e)
        return FALLBACK_M3U

    # Se for live, info pode ter 'is_live' True — a lógica é a mesma
    try:
        chosen = choose_best_stream_url(info)
        return chosen
    except Exception as e:
        logging.debug("Erro a escolher stream para %s : %s", url, e)
        # fallback simples
        if info.get("url"):
            return info.get("url")
        return FALLBACK_M3U


def process_file(infile: str, outfile, cookiefile: Optional[str]) -> None:
    if not os.path.exists(infile):
        raise FileNotFoundError(infile)

    with open(infile, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.rstrip("\n") for ln in f]

    outfile.write('#EXTM3U"\n')

    for line in lines:
        line = line.strip()
        if not line or line.startswith("~~"):
            continue

        if "|" in line and not line.lower().startswith("http"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4:
                ch_name = parts[0]
                grp_title = parts[1].title()
                tvg_logo = parts[2]
                tvg_id = parts[3]
                outfile.write(f'\n#EXTINF:-1 group-title="{grp_title}" tvg-logo="{tvg_logo}" tvg-id="{tvg_id}",{ch_name}\n')
                continue
            else:
                outfile.write(f'\n# {line}\n')
                continue

        if line.lower().startswith("http"):
            logging.info("Processando URL: %s", line)
            stream = extract_stream_with_yt_dlp(line, cookiefile=cookiefile)
            outfile.write(stream + "\n")
        else:
            continue

    outfile.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gerar M3U com melhor qualidade disponível (usa yt-dlp).")
    parser.add_argument("-i", "--input", default="../youtube_channel_info.txt", help="Ficheiro de input (default ../youtube_channel_info.txt)")
    parser.add_argument("-o", "--output", default=None, help="Ficheiro de output (se omitido escreve para stdout)")
    parser.add_argument("--timeout", type=int, default=15, help="Timeout para yt-dlp (segundos)")
    parser.add_argument("--debug", action="store_true", help="Ativa logging debug")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="[%(levelname)s] %(message)s")

    cookies_text = os.environ.get("YT_COOKIES", "") or os.environ.get("YOUTUBE_COOKIES", "")
    cookiefile_path = None
    try:
        if cookies_text:
            cookiefile_path = write_temp_cookies(cookies_text)
            logging.debug("Ficheiro de cookies temporário: %s", cookiefile_path)
        else:
            logging.debug("Sem cookies fornecidos; a correr sem autenticação.")

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
        if cookiefile_path:
            remove_file_silent(cookiefile_path)
            logging.debug("Ficheiro de cookies temporário removido.")


if __name__ == "__main__":
    main()

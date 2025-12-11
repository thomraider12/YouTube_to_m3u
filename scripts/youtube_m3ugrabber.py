#!/usr/bin/env python3
# coding: utf-8

"""
youtube_to_m3u.py
Versão melhorada do teu script para extrair links .m3u8 e gerar uma lista M3U.
Uso: python3 youtube_to_m3u.py -i ../youtube_channel_info.txt -o canais.m3u
"""

from __future__ import annotations
import argparse
import logging
import os
import re
import sys
import time
from typing import Optional, List
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter, Retry

# Optional dependencies
try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None  # fallback

try:
    from tqdm import tqdm  # type: ignore
except Exception:
    tqdm = None

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

FALLBACK_M3U = 'https://raw.githubusercontent.com/benmoose39/YouTube_to_m3u/main/assets/moose_na.m3u'

URL_RE = re.compile(r'https?://[^\s"\'<>#]+?\.m3u8', re.IGNORECASE)
SIMPLE_URL_RE = re.compile(r'https?://[^\s"\'<>]+', re.IGNORECASE)


def build_session(timeout: int = 15) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    retries = Retry(total=2, backoff_factor=0.5,
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "HEAD"])
    s.mount('https://', HTTPAdapter(max_retries=retries))
    s.mount('http://', HTTPAdapter(max_retries=retries))
    s.request_timeout = timeout  # attribute for convenience
    return s


def find_m3u8_in_text(text: str, base_url: Optional[str] = None) -> Optional[str]:
    # 1) direct regex for absolute .m3u8
    m = URL_RE.search(text)
    if m:
        return m.group(0)

    # 2) try to locate .m3u8 with surrounding context and extract https://... portion
    idx = text.lower().find('.m3u8')
    if idx != -1:
        # expand window
        start = max(0, idx - 400)
        end = min(len(text), idx + 20)
        window = text[start:end]
        # find the last "http" in the window
        http_idx = window.rfind('http')
        if http_idx != -1:
            candidate = window[http_idx:].split()[0].strip('\'"<>),;')
            if candidate.lower().endswith('.m3u8'):
                return candidate

    # 3) if base_url present, search for relative urls ending with .m3u8
    if base_url:
        # look for hrefs or src attributes that include .m3u8
        rel_re = re.compile(r'(?:href|src)=["\']([^"\']+\.m3u8)["\']', re.IGNORECASE)
        m2 = rel_re.search(text)
        if m2:
            return urljoin(base_url, m2.group(1))

    # 4) give up
    return None


def try_extract_via_bs4(text: str, base_url: Optional[str] = None) -> Optional[str]:
    if not BeautifulSoup:
        return None
    try:
        soup = BeautifulSoup(text, 'html.parser')
        # check <video> <source> tags
        for source in soup.find_all('source'):
            src = source.get('src') or source.get('data-src')
            if src and src.lower().endswith('.m3u8'):
                return urljoin(base_url or '', src)
        # check <iframe> and <link> tags too
        for tag in soup.find_all(['iframe', 'link', 'a']):
            src = tag.get('src') or tag.get('href') or tag.get('data-src')
            if src and '.m3u8' in src:
                return urljoin(base_url or '', src)
    except Exception:
        return None
    return None


def grab_m3u8(session: requests.Session, url: str, timeout: int = 15) -> str:
    """
    Tentativa segura de obter um link .m3u8 a partir de uma URL.
    Retorna o link .m3u8 encontrado ou o FALLBACK_M3U se falhar.
    """
    url = url.strip()
    if not url:
        return FALLBACK_M3U

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else None

    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        text = r.text
    except Exception as e:
        logging.debug("Erro ao GET %s : %s", url, e)
        # última tentativa: usar curl via sistema (apenas se existir) — mas evitamos por segurança
        return FALLBACK_M3U

    # procurar por .m3u8
    link = find_m3u8_in_text(text, base_url=url)
    if link:
        return link

    # tentar com bs4
    link = try_extract_via_bs4(text, base_url=url)
    if link:
        return link

    # procurar todos os URLs e ver se algum termina em .m3u8 depois de juntar possibilmente
    all_urls = SIMPLE_URL_RE.findall(text)
    for candidate in all_urls:
        if candidate.lower().endswith('.m3u8'):
            # normalizar
            if candidate.startswith('//'):
                candidate = f'{parsed.scheme}:{candidate}'
            return candidate

    # Se nada foi encontrado, procurar em scripts externos referenciados na página
    # buscar src de scripts e pedir cada um (limitado a 5)
    script_srcs = []
    if BeautifulSoup:
        try:
            soup = BeautifulSoup(text, 'html.parser')
            for s in soup.find_all('script', src=True):
                script_srcs.append(urljoin(url, s['src']))
        except Exception:
            script_srcs = []
    # tentar alguns scripts
    for s_url in script_srcs[:5]:
        try:
            r2 = session.get(s_url, timeout=timeout)
            link = find_m3u8_in_text(r2.text, base_url=s_url)
            if link:
                return link
        except Exception:
            continue

    # tudo falhou
    return FALLBACK_M3U


def process_input_file(input_path: str, session: requests.Session, output_stream, timeout: int = 15,
                       concurrency: int = 4, show_progress: bool = True) -> None:
    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)

    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [ln.rstrip('\n') for ln in f]

    # imprimir cabeçalho M3U
    output_stream.write('#EXTM3U x-tvg-url="https://github.com/botallen/epg/releases/download/latest/epg.xml"\n')
    output_stream.write(BANNER + '\n')

    # simples state machine: quando encontra uma linha de metadados imprime EXTINF; quando encontra URL -> faz grab e imprime URL
    tasks = []
    i = 0

    if tqdm and show_progress:
        iterator = tqdm(range(len(lines)), desc='Processando', unit='lin')
    else:
        iterator = range(len(lines))

    for idx in iterator:
        line = lines[idx].strip()
        if not line or line.startswith('~~'):
            continue

        # se for uma linha de metadados (contém pipes e não começa por http)
        if not line.lower().startswith('http'):
            # suporta o teu formato: "Name | group | logo | id"
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 4:
                ch_name = parts[0]
                grp_title = parts[1].title()
                tvg_logo = parts[2]
                tvg_id = parts[3]
                output_stream.write(f'\n#EXTINF:-1 group-title="{grp_title}" tvg-logo="{tvg_logo}" tvg-id="{tvg_id}", {ch_name}\n')
            else:
                # se não for no formato esperado, imprime como comentário
                output_stream.write(f'\n# {line}\n')
        else:
            # linha é uma URL — tentamos extrair .m3u8 e escrevê-la
            try:
                link = grab_m3u8(session, line, timeout=timeout)
                output_stream.write(link + '\n')
            except Exception as e:
                logging.debug("Erro ao processar %s : %s", line, e)
                output_stream.write(FALLBACK_M3U + '\n')

    output_stream.flush()


def main(argv=None):
    p = argparse.ArgumentParser(description='Extrai links .m3u8 de páginas e gera um ficheiro M3U.')
    p.add_argument('-i', '--input', default='../youtube_channel_info.txt', help='Ficheiro de input com lista de canais (default ../youtube_channel_info.txt)')
    p.add_argument('-o', '--output', default=None, help='Ficheiro de output (se omitido escreve para stdout)')
    p.add_argument('-t', '--timeout', type=int, default=12, help='Timeout em segundos para requests (default 12)')
    p.add_argument('-c', '--concurrency', type=int, default=4, help='Número de workers (não usado intensivamente aqui)')
    p.add_argument('--no-progress', action='store_true', help='Não mostrar barra de progresso')
    p.add_argument('--debug', action='store_true', help='Ligar logging debug')
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format='[%(levelname)s] %(message)s')

    session = build_session(timeout=args.timeout)

    if args.output:
        out_dir = os.path.dirname(os.path.abspath(args.output))
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        with open(args.output, 'w', encoding='utf-8') as out_f:
            process_input_file(args.input, session, out_f, timeout=args.timeout,
                               concurrency=args.concurrency, show_progress=not args.no_progress)
        logging.info('Escrito ficheiro: %s', args.output)
    else:
        process_input_file(args.input, session, sys.stdout, timeout=args.timeout,
                           concurrency=args.concurrency, show_progress=not args.no_progress)


if __name__ == '__main__':
    main()

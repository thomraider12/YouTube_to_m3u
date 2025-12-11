#!/usr/bin/python3
import os
import sys
from yt_dlp import YoutubeDL

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

FALLBACK = "https://raw.githubusercontent.com/benmoose39/YouTube_to_m3u/main/assets/moose_na.m3u"


def extract_m3u8(url: str) -> str:
    """
    Usa a API do yt-dlp para tentar extrair link HLS (.m3u8).
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "dump_single_json": True,
    }

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # procurar formatos com .m3u8
        for f in info.get("formats", []):
            stream_url = f.get("url", "")
            if ".m3u8" in stream_url:
                return stream_url

        # Se não houver .m3u8, ao menos devolve o melhor link direto
        if "url" in info:
            return info["url"]

        return FALLBACK

    except Exception:
        return FALLBACK


def main():
    print('#EXTM3U x-tvg-url="https://github.com/botallen/epg/releases/download/latest/epg.xml"')
    print(BANNER)

    txt_path = "../youtube_channel_info.txt"

    if not os.path.exists(txt_path):
        print("Ficheiro youtube_channel_info.txt não encontrado!")
        sys.exit(1)

    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("~~"):
                continue

            # linha com dados do canal
            if "|" in line:
                ch_name, grp_title, tvg_logo, tvg_id = [p.strip() for p in line.split("|")]
                print(f'\n#EXTINF:-1 group-title="{grp_title.title()}" tvg-logo="{tvg_logo}" tvg-id="{tvg_id}", {ch_name}')
                continue

            # linha com URL → extrair stream
            if line.startswith("https:"):
                stream = extract_m3u8(line)
                print(stream)


if __name__ == "__main__":
    main()

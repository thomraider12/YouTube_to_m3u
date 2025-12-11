#!/bin/bash

echo $(dirname $0)

python3 -m pip install requests beautifulsoup4 tqdm

cd $(dirname $0)/scripts/

python3 youtube_m3ugrabber.py -i ../youtube_channel_info.txt -o canais.m3u

echo m3u grabbed

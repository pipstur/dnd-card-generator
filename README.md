# D&D Card Generator

Generate printable D&D 5e spell and item cards, complete with AI-generated item illustrations. The project includes a web scraper, a local image-generation pipeline, and a vector-based card and PDF generator.

## Features

- Generate spell and magic item cards from JSON or CSV.
- Automatically generate item illustrations locally using ComfyUI and Ollama.
- Export individual SVG cards and a print-ready, vector PDF.
- Print poker-size cards (2.5 × 3.5 inches), arranged 3 × 3 on US Letter pages.
- Customize card colors, item artwork, and card data.
- Scrape spells and wondrous items from [dnd5e.wikidot.com](https://dnd5e.wikidot.com).

## Requirements

- Windows 10/11
- NVIDIA GPU with a compatible driver
- Python 3.10+

For generating AI item illustrations, the following are also required:
- Sufficient disk space for ComfyUI and its models (about 10GB)
- RTX 3090 or equivalent GPU with at least 24GB VRAM for the default Ollama model. Smaller models can be used on GPUs with less VRAM. You can try to adjust this.


The included setup script downloads ComfyUI and the required image-generation models. Ollama must also be installed for automatic item-description generation.

## Quick start
**0. Optional, only for card generation:**
If you want to generate item illustrations using ComfyUI and Ollama, run or double-click the setup script from the project directory:

```bat
setup.bat
```

The script downloads and extracts ComfyUI, installs the required models, and prepares the environment. Follow the instructions.

**1. Set up the project**
Create a python virtual environment:

```bash
python -m venv venv
venv\Scripts\activate # Windows PowerShell
source venv/Scripts/activate # Windows bash
source venv/bin/activate # Linux / macOS
```
Install the required packages:

```bash
pip install -r requirements.txt
```

**2. Start generating cards**
Generate cards from the included data:

```bash
python main.py \
--spells output/dnd5e_spells.csv \
--items output/dnd5e_wondrous_items.csv
```
If you want to use black-and-white cards for better printing without color, add the `--bw` option:
```bash
python main.py \
--spells output/dnd5e_spells.csv \
--items output/dnd5e_wondrous_items.csv \
--bw
```

The generated files are saved to:

- `output/svg/` — individual SVG cards
- `output/cards.pdf` — print-ready PDF

Print the PDF at **100% scale** with “Fit to page” disabled.

**3. Generate item illustrations**
I've included a zip with the [pre-generated item illustrations](https://github.com/pipstur/dnd-card-generator/releases/tag/v1.0) which you can download and extract to `output/item_images/`. There is 3 versions of each item generated, you can take a look at them and if you find a particular one you like, just rename that file to remove the version suffix (example: `item_1.png` -> `item.png`). These can be used for the item cards in the `main.py` script.

If you want to generate your own illustrations, follow the instructions below.
If you've run the setup script, you can generate item illustrations for the wondrous items. The script uses ComfyUI and Ollama to generate images based on the scraped item descriptions.

Start Ollama (run the app) and ComfyUI server (double click the `ComfyUI_windows_portable/run_nvidia_gpu.bat` file), then run:

```bash
python generate_item_images.py --config config/item_generation.json
```

Existing images are skipped, so interrupted runs can be resumed. The generated illustrations are saved to `output/item_images/`.

Generate multiple variants per item:

```bash
python generate_item_images.py --variants 3
```

## Homebrew / custom cards
The repository includes sample and custom data files:

- `config/spells_custom.json` — spell cards
- `config/items_custom.json` — item cards
- CSV files — scraped spell and wondrous-item data (in the `output/` folder)
- `config/` — image-generation settings and ComfyUI workflow

To use your own data:

```bash
python main.py --spells config/spells_custom.json --items config/items_custom.json
```

Supported input formats are JSON and CSV. See the included sample files for the required fields.

This can be used to create custom cards for homebrew spells and items, or to modify the included data.

### Useful options

```bash
python main.py --no-items # do not include item cards
python main.py --no-spells # do not include spell cards
python main.py --bw # black and white
python main.py --no-pdf # do not generate the pdf, only svgs
python main.py --no-svg # do not generate the svgs, only the pdf
python main.py --copies 3 # print 3 copies of each item or spell, if you want to hand them out to multiple players/campaigns
```

For custom output paths and other options, run:

```bash
python main.py --help
python generate_item_images.py --help
```

## Scrape updated D&D data

The included scraper downloads spell and wondrous-item data into CSV files.

```bash
python dnd5e_scraper.py
python dnd5e_scraper.py spells
python dnd5e_scraper.py items
```

Use the included CSV files directly if you don't need to refresh the data.

## Troubleshooting
- **Missing models:** rerun `setup.bat` to check and download missing files.
- **Out of GPU memory:** close other GPU-intensive applications or use a smaller Ollama model.
- **Failed image generation:** check `output/generation_log.jsonl` for errors.
- **Incorrect card artwork:** check the image filenames and item names.
- **Missing dependencies:** ensure the project environment is activated and install the packages from `requirements.txt`.

## Preview of generated cards
Note: These are JPEG images of the generated cards, not the actual cards themselves. The actual cards are generated as SVGs and a PDF in the `output/` folder. 
### Spells
![Spells](https://i.imgur.com/UO8ME1o.jpeg)

### Common Wondrous Items
![Common Wondrous Items](https://i.imgur.com/NuCzczG.jpeg)

### Uncommon Wondrous Items
![Uncommon Wondrous Items](https://i.imgur.com/mNTAvMk.jpeg)

### Rare Wondrous Items
![Rare Wondrous Items](https://i.imgur.com/7CGRndg.jpeg)

### Very Rare Wondrous Items
![Very Rare Wondrous Items](https://i.imgur.com/7JLPYfp.jpeg)

### Legendary Wondrous Items
![Legendary Wondrous Items](https://i.imgur.com/X7OlM2d.jpeg)

## Credits and licensing

This project uses [ComfyUI](https://github.com/Comfy-Org/ComfyUI), [Ollama](https://ollama.com/), and third-party AI models. Refer to their respective licenses and terms before redistributing model files or using generated assets commercially.

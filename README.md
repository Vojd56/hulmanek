# Hulmánek: kdo je kdo ve výběhu hulmanů

> **Neoficiální studentský projekt.** Vznikl pro potřeby chovatelů hulmanů v Zoo Ostrava,
> ale není oficiálním produktem, službou ani stránkou Zoo Ostrava a zoo za něj neodpovídá.
> Vzhled je inspirovaný webem zoo, loga a ochranné známky zoo se nepoužívají.

Vyfotíte nebo natočíte hulmana telefonem a aplikace řekne, jak se jmenuje.
Pozná ho podle obličeje i podle celého těla (bok, záda) a u videa hlasuje přes víc snímků.
Vše běží na vašem počítači v zoo, fotky nikam neodcházejí. Celé řešení je open source.

## Proč lokální web na PC, a ne aplikace v telefonu

| | Web na PC s RTX 3060 (zvoleno) | Model přímo v telefonu |
|---|---|---|
| iPhone i Android | ano, stačí prohlížeč | dvě aplikace nebo Flutter, App Store / TestFlight |
| Přesnost | velký model MegaDescriptor-L-384 + YOLO-World x | jen menší modely, přesnost nižší |
| Galerie všech hulmanů | jedna společná pro všechny ošetřovatele | každý telefon má svou kopii, nutná synchronizace |
| Doladění na vašich hulmanech | na stejném počítači, hned se použije | trénink stejně na PC, pak export a nová verze aplikace |
| Bez Wi-Fi ve výběhu | ne (řešení: Tailscale / mobilní data) | ano |

Rozhodující je, že model se musí trénovat na vašem PC tak jako tak a že galerie se
neustále rozrůstá potvrzenými záběry. Proto je centrum na počítači a telefon je jen „kamera
a displej“. Kdyby později bylo potřeba rozpoznávat úplně offline, dá se doladěný model
převést do Core ML (iPhone) a TFLite (Android) jako druhá fáze.

## Jak to funguje

1. **Detekce**: [YOLO-World](https://docs.ultralytics.com/models/yolo-world/) najde na snímku
   hulmana (celé tělo) a jeho obličej. Třídy se zadávají textem, nic se netrénuje.
2. **Otisk**: [MegaDescriptor](https://huggingface.co/BVRA/MegaDescriptor-L-384) (ČVUT Praha,
   projekt WildlifeDatasets) převede výřez obličeje i těla na číselný otisk.
3. **Porovnání**: otisk se porovná se všemi uloženými výřezy každého hulmana. Skóre jedince je
   průměr jeho 3 nejpodobnějších výřezů; obličej i tělo mají výchozí váhu 50 % (lze změnit v záložce Stav).
4. **Video**: bere 2 snímky za sekundu (max. 40) a výsledky průměruje.
5. **Učení za provozu**: když výsledek potvrdíte, výřezy se přidají do galerie.
6. **Doladění**: `scripts/finetune.py` doladí MegaDescriptor přímo na vašich hulmanech (ArcFace).

## Instalace (Windows, RTX 3060)

1. Nainstalujte [Python 3.12](https://www.python.org/downloads/) (zaškrtněte „Add python.exe to PATH“).
2. Rozbalte složku `hulmanek` třeba do `C:\hulmanek`.
3. Spusťte `install_windows.bat` (stáhne PyTorch s CUDA a knihovny, cca 4 GB).
4. Spusťte `start_windows.bat`. Při prvním spuštění se stáhnou modely (cca 1 GB).
   Windows se zeptá na firewall: povolte **soukromé sítě**.
5. V okně se vypíše adresa, např. `http://192.168.1.20:8000`. Otevřete ji v Safari na iPhonu
   (telefon musí být na stejné Wi-Fi) a dejte **Sdílet → Přidat na plochu**. Pak se chová jako aplikace.

Linux: `./install_linux.sh` a `./start_linux.sh`.

### PIN
Aby aplikaci nemohl používat kdokoli na Wi-Fi, nastavte před spuštěním PIN:
do `start_windows.bat` odkomentujte řádek `set HULMANY_PIN=1234`.

### Přístup mimo Wi-Fi zoo
Nainstalujte [Tailscale](https://tailscale.com/) na počítač i telefon (zdarma pro osobní použití).
Telefon pak na aplikaci dosáhne odkudkoli přes šifrované spojení, bez otevírání portů do internetu.

## Postup naplnění dat

1. V záložce **Hulmani** přidejte jména všech hulmanů.
2. Ke každému nahrajte fotky a hlavně krátká videa (z videa se bere 1 snímek za sekundu).
   Cíl je 100+ záběrů na hulmana: obličej, oba boky, záda, různé dny a světlo.
   Na záběru má být ideálně jen ten jeden hulman.
3. Hromadně z počítače: připravte složku `fotky/Jméno/*.jpg|mp4` a spusťte
   `python scripts/import_folders.py fotky` (aplikace musí běžet).
4. V záložce **Stav** klikněte na **Vyhodnotit přesnost**. Uvidíte, jak často je správný hulman
   na 1. místě, a doporučený práh pro „neznámý hulman“.
5. Pak doladění (na počítači, v aktivovaném prostředí `.venv\Scripts\activate`):
   ```
   python scripts/finetune.py
   ```
   Na RTX 3060 to s ~2 500 záběry trvá zhruba desítky minut. Skript vypíše přesnost před a po
   doladění a uloží jen lepší model. Pak v **Stav** klikněte **Načíst doladěný model**.
   Když dojde paměť GPU, použijte `--batch 8`.

## Nastavení (proměnné prostředí)

| Proměnná | Výchozí | Význam |
|---|---|---|
| `HULMANY_EMBEDDER` | `auto` | `L-384` (GPU), `B-224`, `T-224` (CPU) |
| `HULMANY_DETECTOR_WEIGHTS` | `auto` | `yolov8x-worldv2.pt` (GPU) / `yolov8s-worldv2.pt` (CPU) |
| `HULMANY_DETECTOR` | `1` | `0` = bez detektoru, porovnává se celý snímek |
| `HULMANY_FACE_WEIGHT` | `0.5` | váha obličeje proti tělu (lze měnit i v aplikaci) |
| `HULMANY_THRESHOLD` | `0.55` | práh pro „neznámý hulman“ (lze měnit i v aplikaci) |
| `HULMANY_VIDEO_FPS` | `2` | kolik snímků za sekundu brát z videa |
| `HULMANY_PIN` | prázdné | PIN pro přístup |
| `HULMANY_DATA_DIR` | `data/` | databáze a fotky (zálohujte tuto složku) |

## Struktura

```
app/          server (FastAPI): detekce, otisky, galerie, API
static/       mobilní webové rozhraní (PWA, bez sestavování)
scripts/      finetune.py (doladění), import_folders.py (hromadný import)
tests/        automatické testy (python -m pytest tests)
data/         vzniká za běhu: hulmany.db + media/ (ZÁLOHUJTE)
models/       doladěné modely
```

## Obličej vs. tělo

Každý výřez je buď **obličej**, nebo **tělo** a porovnává se jen se stejným druhem
(obličej s obličeji, tělo s těly). Na tom záleží: fotka těla uložená jako obličej se pak
porovnává se špatnou skupinou a zhoršuje výsledky. Druh určuje detektor automaticky; když se
splete, klepněte na výřez (u výsledku před potvrzením, nebo v galerii hulmana) a přepněte ho.

Hulmani mají černé obličeje, které jsou si navzájem dost podobné, takže u nich budou hodně
rozhodovat tělo, ocas, jizvy a postava. Výchozí váha je proto 50 : 50 a dá se upravit
v záložce **Stav** podle toho, co vyjde ve **Vyhodnotit přesnost**.

## Co je dobré vědět

- Detektor YOLO-World je obecný. Pokud v praxi špatně hledá obličeje hulmanů, nejrychlejší
  zlepšení je natrénovat malý vlastní detektor (YOLO) na pár stovkách ručně označených snímků.
  Aplikace funguje i bez detektoru, jen porovnává celý snímek.
- Ultralytics (YOLO-World) má licenci AGPL-3.0, pro vnitřní použití v zoo to nevadí;
  MegaDescriptor je CC BY-NC 4.0, tedy pro nekomerční použití.
- Mláďata se v čase mění: přidávejte jim nové záběry průběžně.
- Kontakty pro spolupráci: tým WildlifeDatasets (ČVUT / ZČU), HPI + Zoo Berlin (Gorilla Tracker).

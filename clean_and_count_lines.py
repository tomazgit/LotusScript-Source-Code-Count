"""
Author: Tomaž, v0.1.0, 24.11.2025.
Description:
  Clean and count lines in LotusScript / DXL files from a given folder.
  - Ignores certain extensions and files with specific headers (e.g., images).
  - From XML files, extracts only certain "interesting" tags (e.g., lotusscript, formula, rawitemdata).
  - Considers global and per-extension blocking of certain XML tags.
  - Finally, prints processing statistics.
  There are many things to improve, but this is the base.

Usage:
    python clean_and_count_lines.py [input_folder]
If input_folder is not provided, the default (DEFAULT_SOURCE_DIR) is used.
"""

import os
import sys
import shutil
import base64
from typing import Dict, Set, List

# ==========================
# KONFIGURACIJA
# ==========================

# Privzeta vhodna mapa, če ne podamo parametra
DEFAULT_SOURCE_DIR = r"c:\test"

# Tag-i, ki so nam (zaenkrat) zanimivi za izvoz iz XML (npr. LotusScript, raw objekti)
INTERESTING_XML_TAGS: Set[str] = {
    "lotusscript",
    "formula",
    "rawitemdata",
    "java",
}

# Mape (relativno na source_root), v katerih štejemo število datotek
INTERESTING_SOURCE_SUBDIRS: List[str] = [
    r"Forms",
    r"Views",
    r"Folders",
    r"Framesets",
    r"Pages",
    r"SharedElements\Subforms",
    r"SharedElements\Fields",
    r"SharedElements\Columns",
    r"SharedElements\Outlines",
    r"Code\Agents",
    r"Code\ScriptLibraries",
    # dodaj po potrebi ...
]


# Končnice datotek, ki jih ignoriramo (se NE kopirajo / obdelujejo)
IGNORE_EXTENSIONS: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".metadata",
    ".xml",
}

# NOVE: končnice datotek, ki jih ŽELIMO vedno obdelati kot navaden tekst
# (tudi če niso XML) in jim pobrisati prazne vrstice.
ALWAYS_PROCESS_AS_TEXT_EXTENSIONS: Set[str] = {
    ".lss",
    ".lsa",
}

# Headerji (magic bytes) datotek, ki jih ignoriramo ne glede na končnico
# (tu samo nekaj primerov – lahko jih poljubno dodajaš)
IGNORE_MAGIC_PREFIXES: List[bytes] = [
    b"GIF89",                     # GIF
    b"\x89PNG",                   # PNG (‰PNG)
    bytes.fromhex("FFD8FFE000104A464946"),  # JPEG JFIF FF D8 FF E0 00 10 4A 46 49 46
]

# Globalni XML tagi, ki jih hočemo blokirati v vseh XML datotekah
GLOBAL_BLOCKED_TAGS: Set[str] = {
    # primeri – dopolni po želji:
    # "noteinfo",
    # "updatedby",
    # "revisions",
}

# Posebni XML tagi, ki jih blokiramo samo za določene končnice
# ključ = končnica datoteke (z začetno piko, npr. ".form", ".column")
PER_EXTENSION_BLOCKED_TAGS: Dict[str, Set[str]] = {
    # ".column": {"nekTag", "drugTag"},
    # ".form": {"actionbar", "body"},
}
ZNANE_XML_DATOTEKE: Set[str] = {
    ".fa", ".form", ".column", ".wsdl", ".lsdb",
    ".folder", ".form", ".formset", ".page", ".view", ".field",
    ".outline", ".subform", ".javalib",
}
# ==========================
# POMOŽNE FUNKCIJE – FILE SYSTEM
# ==========================

def ensure_dir(path: str) -> None:
    """Poskrbi, da mapa obstaja."""
    os.makedirs(path, exist_ok=True)


def build_export_root(source_root: str) -> str:
    """Iz vhodne poti zgradi ime izhodne mape: <pot>-export."""
    # odstrani morebiten zaključen separator zaradi lepšega imena
    source_root_clean = source_root.rstrip("\\/")
    return source_root_clean + "-export"


def get_rel_path(base: str, full: str) -> str:
    """Vrne relativno pot `full` glede na `base`."""
    rel = os.path.relpath(full, base)
    # če smo v korenu, vrne "."
    return rel


def copy_file(src: str, dst: str) -> None:
    """Navaden copy (trenutna 'obdelava' datoteke)."""
    ensure_dir(os.path.dirname(dst))
    shutil.copy2(src, dst)


# ==========================
# IGNORIRANJE PO KONČNICI / HEADERJU
# ==========================

def should_skip_by_extension(path: str) -> bool:
    """Preveri, ali datoteko ignoriramo glede na končnico."""
    _, ext = os.path.splitext(path)
    return ext.lower() in IGNORE_EXTENSIONS


def read_header(path: str, length: int = 32) -> bytes:
    """Prebere prvih N bajtov iz datoteke (za header preverjanje)."""
    try:
        with open(path, "rb") as f:
            return f.read(length)
    except OSError:
        return b""


def starts_with_any(data: bytes, prefixes: List[bytes]) -> bool:
    """Vrne True, če `data` začne s katerimkoli prefixom."""
    for p in prefixes:
        if data.startswith(p):
            return True
    return False


def should_skip_by_header(path: str) -> bool:
    """Preveri, ali datoteko ignoriramo glede na magic header."""
    header = read_header(path, length=max(len(x) for x in IGNORE_MAGIC_PREFIXES))
    if not header:
        return False
    return starts_with_any(header, IGNORE_MAGIC_PREFIXES)


# ==========================
# XML POMOČNIKI
# ==========================

def is_probably_xml(path: str) -> bool:
    """
    Zelo enostavna detekcija, ali je datoteka verjetno XML:
    - po končnici (.xml, .dxl, .form, .column, ...)
    - ali pa če se začne z '<?xml' oziroma '<'
    """
    _, ext = os.path.splitext(path)
    if ext.lower() in ZNANE_XML_DATOTEKE:
        return True

    try:
        with open(path, "rb") as f:
            head = f.read(128)
        text = head.decode("utf-8", errors="ignore").lstrip()
        return text.startswith("<?xml") or text.startswith("<")
    except OSError:
        return False


def load_xml_text(path: str) -> str:
    """Prebere datoteko kot tekst (utf-8 z rezervno varianto)."""
    with open(path, "rb") as f:
        data = f.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin1", errors="replace")


def get_local_tag(tag: str) -> str:
    """
    Iz XML tag-a odstrani namespace, npr:
    '{http://www.lotus.com/dxl}form' -> 'form'
    """
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def is_blocked_tag(local_tag: str, ext: str) -> bool:
    """
    Ali je tag blokiran glede na globalno in per-ekstenzija nastavitve.
    """
    if local_tag in GLOBAL_BLOCKED_TAGS:
        return True
    extra = PER_EXTENSION_BLOCKED_TAGS.get(ext.lower(), set())
    if local_tag in extra:
        return True
    return False


def is_empty_line(text: str) -> bool:
    """Vrne True, če je vrstica prazna ali vsebuje samo presledke, tabulatorje ali newline znake."""
    return text.strip() == ""


def remove_empty_lines_normalized(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines()
        if not is_empty_line(line)
    )


# --- NOVO: dekodiranje rawitemdata (base64) in odločanje, ali je tekst ali binarno ---

def decode_rawitemdata_base64(raw: str) -> str | None:
    """
    Poskusi base64-dekodirati rawitemdata.
    Če rezultat deluje kot tekst (koda), vrne string.
    Če gre za binarne podatke ali dekodiranje ne uspe, vrne None.
    """
    # odstrani whitespace (newline, presledki, ...)
    clean = "".join(raw.split())
    if not clean:
        return None

    # poskus dekodiranja base64
    try:
        decoded = base64.b64decode(clean, validate=True)
    except Exception:
        return None

    if not decoded:
        return None

    # Heuristika: če je preveč ne-tiskljivih znakov ali null byte-ov, tretiramo kot binarno
    head = decoded[:64]
    if head:
        non_text = 0
        for b in head:
            if b == 0:
                non_text += 1
            elif b < 9:
                non_text += 1
            elif 14 <= b < 32:
                non_text += 1
        ratio = non_text / len(head)
        if ratio > 0.30:
            return None

    # poskus dekodiranja v tekst
    try:
        txt = decoded.decode("utf-8")
    except UnicodeDecodeError:
        txt = decoded.decode("latin1", errors="replace")

    # normalizacija in čiščenje
    txt = txt.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not txt:
        return None

    return txt


def extract_interesting_xml_fragments(xml_text: str, file_ext: str, stats: Dict[str, int]) -> str:
    """
    Iz XML teksta izlušči samo 'zanimive' fragmente (INTERESTING_XML_TAGS),
    pri čemer upošteva GLOBAL_BLOCKED_TAGS in PER_EXTENSION_BLOCKED_TAGS.
    Zaenkrat vrne preprost tekstovni izpis.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # če XML ni veljaven, vrnemo kar original
        return xml_text

    lines: List[str] = []

    # ElementTree v stdlib nima getparent, tako da bomo path gradili ročno
    # z enostavno rekurzijo, kjer si zapomnimo pot.
    def walk(elem, path_stack: List[str]):
        local = get_local_tag(elem.tag)
        path_stack.append(local)

        # samo, če NI blokiran in če je tag "zanimiv"
        if not is_blocked_tag(local, file_ext) and local in INTERESTING_XML_TAGS:
            if local == "rawitemdata":
                raw = (elem.text or "").strip()
                if raw:
                    decoded = decode_rawitemdata_base64(raw)
                    if decoded is not None:
                        stats["rawitemdata_text"] += 1
                        lines.append(remove_empty_lines_normalized(decoded))
                    else:
                        stats["rawitemdata_binary_or_failed"] += 1
                # če je prazno ali binarno, ne dodamo nič v lines
            else:
                text = (elem.text or "").strip()
                if text:
                    cleaned = remove_empty_lines_normalized(text)
                    if cleaned:
                        lines.append(cleaned)

                        # NOVO: če je to <java> tag, preštej vrstice po čiščenju
                        if local == "java":
                            stats["java_lines"] += sum(
                                1 for _ in cleaned.splitlines()
                            )

        # rekurzivno po otrocih
        for child in list(elem):
            walk(child, path_stack)

        path_stack.pop()

    walk(root, [])

    if not lines:
        # če ni nič zanimivega, se lahko vrne prazno ali fallback
        return ""

    return "\n".join(lines)


def process_xml_file(src: str, dst: str, stats: Dict[str, int]) -> None:
    """
    Procesiranje XML datoteke:
    - prebere XML
    - izlušči zanimive delčke (lotusscript, rawitemdata, ...)
    - upošteva blokiranje tagov
    - rezultat zapiše v `dst`
    """
    xml_text = load_xml_text(src)
    extracted = extract_interesting_xml_fragments(xml_text, os.path.splitext(src)[1], stats)

    ensure_dir(os.path.dirname(dst))

    # Zaenkrat: če smo kaj dobili, zapišemo samo te delčke;
    # če ne, datoteka sploh ne nastane (prazno = brez datoteke).
    if extracted:
        with open(dst, "w", encoding="utf-8", errors="replace") as f:
            f.write(extracted)
    #else:
        # fallback – če ni nič "zanimivega", lahko:
        # - zapišemo original
        # - ali pustimo datoteko prazno
        # Zaenkrat izberimo original:
        #with open(dst, "w", encoding="utf-8", errors="replace") as f:
        #    f.write(xml_text)

    stats["xml_files"] += 1
    stats["processed_files"] += 1
    return


def process_plain_text_file(src: str, dst: str, stats: Dict[str, int]) -> None:
    """
    Obdelava navadne tekstovne datoteke (npr. .lss):
    - prebere vsebino
    - normalizira in odstrani prazne vrstice
    - zapiše v `dst`
    """
    with open(src, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin1", errors="replace")

    cleaned = remove_empty_lines_normalized(text)

    ensure_dir(os.path.dirname(dst))
    with open(dst, "w", encoding="utf-8", errors="replace") as f:
        f.write(cleaned)

    stats["processed_files"] += 1


# ==========================
# GLAVNO PROCESIRANJE POSAMEZNE DATOTEKE
# ==========================

def process_single_file(src: str, dst: str, stats: Dict[str, int]) -> None:
    """Glavna funkcija za obdelavo ene datoteke."""
    stats["total_files"] += 1

    _, ext = os.path.splitext(src)
    ext = ext.lower()

    # 1) ignoriramo po končnici
    if should_skip_by_extension(src):
        stats["skipped_files"] += 1
        stats["skipped_by_ext"] += 1
        return

    # 2) ignoriramo po headerju (magic bytes)
    if should_skip_by_header(src):
        stats["skipped_files"] += 1
        stats["skipped_by_header"] += 1
        return

    # 3) XML obdelava
    if is_probably_xml(src):
        process_xml_file(src, dst, stats)
        return

    # 4) posebne tekstovne datoteke (npr. .lss) – očisti prazne vrstice
    if ext in ALWAYS_PROCESS_AS_TEXT_EXTENSIONS:
        process_plain_text_file(src, dst, stats)
        return

    # 5) vse ostalo (ne-XML in ne na seznamu za tekst) ne kopiramo več
    stats["skipped_files"] += 1
    return


# ==========================
# STATISTIKA
# ==========================

def init_stats() -> Dict[str, int]:
    """Inicializira slovar s statistiko."""
    return {
        "total_files": 0,
        "processed_files": 0,
        "skipped_files": 0,
        "skipped_by_ext": 0,
        "skipped_by_header": 0,
        "xml_files": 0,
        "rawitemdata_text": 0,
        "rawitemdata_binary_or_failed": 0,
        "java_lines": 0,   # NOVO: število vrstic Java kode (po čiščenju)
    }



def print_stats(stats: Dict[str, int]) -> None:
    """Izpiše statistiko obdelave."""
    print("Tu bodo statistični rezultati.")
    print(f"Skupaj datotek:                   {stats['total_files']}")
    print(f"Obdelanih datotek:                {stats['processed_files']}")
    print(f"Preskočenih:                      {stats['skipped_files']}")
    print(f"  - po končnici:                  {stats['skipped_by_ext']}")
    print(f"  - po headerju:                  {stats['skipped_by_header']}")
    print(f"XML datotek:                      {stats['xml_files']}")
    print(f"rawitemdata decodiranih v tekst:  {stats['rawitemdata_text']}")
    print(f"rawitemdata binarnih/neuspešnih:  {stats['rawitemdata_binary_or_failed']}")
    print(f"Vrstice Java kode (po čiščenju):  {stats['java_lines']}")

def count_file_lines(path: str) -> int:
    """
    Prešteje vrstice v datoteki.
    Datoteko odpremo v tekstovnem načinu z utf-8 in ignoriramo
    neveljavne znake, da se ne zaletimo na čudnih encodingih.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        # Če datoteke ne moremo prebrati, jo preskočimo
        return 0


def print_sourceLineCount(export_root: str, statByExtension: bool) -> None:
    """
    Gre čez vse datoteke v export mapi in prešteje vrstice.
    Izpiše:
      - skupno št. datotek
      - skupno št. vrstic
      - razrez po končnicah datotek
    """
    if not os.path.isdir(export_root):
        print(f"\nAnaliza vrstic: export mapa ne obstaja: {export_root}")
        return

    total_files = 0
    total_lines = 0
    lines_by_ext: Dict[str, int] = {}

    for dirpath, dirnames, filenames in os.walk(export_root):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            total_files += 1

            _, ext = os.path.splitext(filename)
            ext = ext.lower() if ext else "<noext>"

            line_count = count_file_lines(full_path)
            total_lines += line_count
            lines_by_ext[ext] = lines_by_ext.get(ext, 0) + line_count

    print("\nAnaliza vrstic v export mapi:")
    print(f"  Export root:            {export_root}")
    print(f"  Število datotek:        {total_files}")
    print(f"  Skupno število vrstic:  {total_lines}")

    if statByExtension:
        if lines_by_ext:
            print("\n  Vrstice po končnicah:")
            for ext, cnt in sorted(lines_by_ext.items(), key=lambda x: (-x[1], x[0])):
                print(f"    {ext}: {cnt}")

def print_number_of_source_files(source_root: str) -> None:
    """
    Na source_root izpiše število datotek v točno določenih podmapah
    (brez rekurzije – samo neposredne datoteke v mapi).
    """
    print("\nŠtevilo datotek v izbranih mapah na source_root:")

    for rel_subdir in INTERESTING_SOURCE_SUBDIRS:
        dir_path = os.path.join(source_root, rel_subdir)

        if not os.path.isdir(dir_path):
            count = 0
        else:
            # samo datoteke v tej mapi, ne rekurzivno
            count = sum(
                1
                for name in os.listdir(dir_path)
                if os.path.isfile(os.path.join(dir_path, name))
            )

        print(f"{rel_subdir}: {count}")

# ==========================
# GLAVNA FUNKCIJA
# ==========================

def process_tree(source_root: str) -> None:
    """Obdela celo drevo map in datotek pod `source_root`."""
    source_root = os.path.abspath(source_root)
    export_root = build_export_root(source_root)

    print(f"Vhodna mapa:  {source_root}")
    print(f"Izhodna mapa: {export_root}")

    stats = init_stats()

    for dirpath, dirnames, filenames in os.walk(source_root):
        rel_dir = get_rel_path(source_root, dirpath)
        # ciljna mapa – enaka struktura kot izvor
        if rel_dir == ".":
            target_dir = export_root
        else:
            target_dir = os.path.join(export_root, rel_dir)

        for filename in filenames:
            src_path = os.path.join(dirpath, filename)
            dst_path = os.path.join(target_dir, filename)
            process_single_file(src_path, dst_path, stats)

    print_stats(stats)
    print_sourceLineCount(build_export_root(source_root), statByExtension=False)
    print_number_of_source_files(source_root)


def main():
    if len(sys.argv) > 1:
        source_root = sys.argv[1]
    else:
        source_root = DEFAULT_SOURCE_DIR

    if not os.path.isdir(source_root):
        print(f"NAPAKA: Mapa ne obstaja: {source_root}")
        return

    process_tree(source_root)


if __name__ == "__main__":
    main()

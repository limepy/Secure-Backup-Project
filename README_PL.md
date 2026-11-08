# Secure Backup Project

[English version](README.md)

**Secure Backup Project** to niewielkie narzędzie wiersza poleceń do tworzenia szyfrowanych i automatycznie weryfikowanych kopii katalogów. Projekt powstaje w ramach przedmiotu **Bezpieczeństwo systemów operacyjnych** i służy do nauki mechanizmów ochrony danych, zarządzania uprawnieniami oraz bezpiecznego odtwarzania kopii.

Docelowa nazwa repozytorium to `Secure_Backup_Project`, a katalog aplikacji to `Secure_Backup`. Jest to projekt akademicki i demonstracyjny, a nie gotowy system backupu przeznaczony do środowiska produkcyjnego.

## Najważniejsze możliwości

- szyfrowanie pełnej kopii przez AES-256-GCM,
- podpis metadanych i szyfrogramu za pomocą Ed25519,
- obliczanie SHA-256 zaszyfrowanego archiwum,
- automatyczne próbne odtworzenie każdej nowej kopii,
- porównanie odtworzonych danych ze źródłem za pomocą manifestu,
- wykrywanie braku zmian bez tworzenia zbędnej wersji,
- niezależna numeracja i rotacja wersji każdego projektu,
- wybór konkretnego projektu i numeru wersji podczas odtwarzania,
- ochrona przed niebezpiecznymi ścieżkami w archiwum TAR,
- prywatny log tekstowy opisujący przebieg operacji,
- restrykcyjne uprawnienia plików i katalogów na Linuksie,
- kontrolowane komunikaty błędów bez śladu stosu.

## System docelowy i kompatybilność

Docelowym środowiskiem jest **Linux** z Pythonem 3.12 lub nowszym. Na Linuksie aplikacja wymaga uruchomienia jako root, korzysta z `umask 077` i kontroluje właściciela oraz uprawnienia kluczy.

Projekt powinien działać również na innych współczesnych dystrybucjach Linuksa, takich jak Debian lub Ubuntu, jeżeli dostępne są Python 3.12+ oraz pakiet `cryptography`.

Możliwe jest uruchomienie kodu i testów na Windows oraz macOS, ale nie daje ono takiego samego modelu bezpieczeństwa:

- kontrola użytkownika root jest wykonywana tylko na Linuksie,
- Windows inaczej interpretuje `chmod` i nie zapewnia uprawnień POSIX 0600/0700,
- zachowanie właścicieli, dowiązań i systemu plików należy ostatecznie sprawdzić na Kali Linux.

## Jak działa aplikacja

Podczas tworzenia kopii program wykonuje następujące kroki:

1. Sprawdza źródło, katalog kluczy, miejsce zapisu i limit wersji.
2. Buduje manifest zawierający względne ścieżki oraz SHA-256 każdego pliku.
3. Odrzuca dowiązania symboliczne i nieobsługiwane typy plików.
4. Porównuje manifest z ostatnią wersją. Jeżeli dane się nie zmieniły, kończy operację bez tworzenia kopii i bez rotacji.
5. Tworzy archiwum TAR w pamięci.
6. Szyfruje archiwum przez AES-256-GCM z nowym losowym nonce.
7. Oblicza SHA-256 szyfrogramu.
8. Podpisuje Ed25519 metadane i sumę szyfrogramu.
9. Zapisuje artefakty w tymczasowym katalogu z prywatnymi uprawnieniami.
10. Sprawdza sumę i podpis, odszyfrowuje kopię, bezpiecznie rozpakowuje TAR i porównuje odzyskany manifest ze źródłem.
11. Dopiero po pełnym sukcesie publikuje nową wersję.
12. Usuwa najstarsze wersje ponad limit `--keep` i zapisuje wynik w logu.

Podczas odtwarzania suma SHA-256 i podpis są sprawdzane przed odszyfrowaniem. Następnie weryfikowany jest tag GCM, bezpieczeństwo wpisów TAR oraz zgodność odzyskanych danych z podpisanym manifestem.

## Format kopii

Każdy katalog źródłowy jest traktowany jako osobny projekt. Nazwa projektu jest pobierana z nazwy katalogu źródłowego.

```text
backups/
└── small/
    ├── 1/
    │   └── backup-20261108T120000000000Z-a1b2c3/
    │       ├── archive.enc
    │       ├── archive.sha256
    │       ├── archive.sig
    │       └── metadata.json
    └── 2/
        └── backup-.../
```

Znaczenie artefaktów:

| Plik | Znaczenie |
|---|---|
| `archive.enc` | Zaszyfrowane archiwum TAR. Pierwsze 12 bajtów zawiera nonce AES-GCM. |
| `archive.sha256` | SHA-256 całego szyfrogramu. |
| `archive.sig` | Podpis Ed25519 metadanych i sumy szyfrogramu. |
| `metadata.json` | Jawny, ale podpisany manifest, ścieżka źródła, projekt i numer wersji. |

Metadane ujawniają nazwy oraz skróty plików. Zawartość plików znajduje się wyłącznie w zaszyfrowanym archiwum.

## Wymagania

- Kali Linux, Debian, Ubuntu lub inny współczesny Linux,
- Python 3.12 lub nowszy,
- pakiet `python3-venv`,
- biblioteka `cryptography`,
- `pytest` do uruchamiania testów.

Zależności znajdują się w `requirements.txt`.

## Bezpieczna instalacja na Kali Linux

Nie należy uruchamiać przez `sudo` środowiska wirtualnego, które może być modyfikowane przez zwykłego użytkownika. Poniższy wariant tworzy oddzielny katalog wdrożeniowy należący do roota:

```bash
cd Secure_Backup

sudo install -d -o root -g root -m 700 /opt/bso-secure-backup
sudo install -o root -g root -m 700 backup.py /opt/bso-secure-backup/backup.py
sudo install -o root -g root -m 600 requirements.txt /opt/bso-secure-backup/requirements.txt

sudo python3 -m venv /opt/bso-secure-backup/.venv
sudo /opt/bso-secure-backup/.venv/bin/pip install \
  -r /opt/bso-secure-backup/requirements.txt

sudo install -d -o root -g root -m 700 \
  /var/lib/bso-secure-backup/source \
  /var/log/bso-secure-backup

sudo cp -a test_data/small /var/lib/bso-secure-backup/source/small
sudo chown -R root:root /var/lib/bso-secure-backup
sudo chmod -R go-rwx /var/lib/bso-secure-backup
```

Jeżeli system nie ma obsługi środowisk wirtualnych:

```bash
sudo apt update
sudo apt install python3-venv
```

Na potrzeby pracy deweloperskiej testy można uruchamiać w zwykłym lokalnym `.venv`, bez `sudo`. Wariant `/opt` służy do bezpieczniejszego uruchamiania aplikacji jako root.

## Szybki start

Poniższe przykłady zakładają instalację aplikacji w `/opt/bso-secure-backup`, dane demonstracyjne w `/var/lib/bso-secure-backup/source` i log w `/var/log/bso-secure-backup`.

### 1. Generowanie kluczy

```bash
sudo /opt/bso-secure-backup/.venv/bin/python \
  /opt/bso-secure-backup/backup.py init-keys \
  --keys /var/lib/bso-secure-backup/keys \
  --log /var/log/bso-secure-backup/backup.log
```

Polecenie tworzy:

- `aes.key` — 256-bitowy klucz AES,
- `private.key` — prywatny klucz Ed25519,
- `public.key` — publiczny klucz Ed25519.

Katalog kluczy musi być pusty. Istniejące klucze nigdy nie są automatycznie nadpisywane.

### 2. Tworzenie kopii

```bash
sudo /opt/bso-secure-backup/.venv/bin/python \
  /opt/bso-secure-backup/backup.py backup \
  --source /var/lib/bso-secure-backup/source/small \
  --output /var/lib/bso-secure-backup/backups \
  --keys /var/lib/bso-secure-backup/keys \
  --keep 3 \
  --log /var/log/bso-secure-backup/backup.log
```

Przykładowy wynik:

```text
BACKUP_OK: small, version 1; restored and compared. Removed versions: []
```

Ponowne uruchomienie bez zmiany danych zwróci:

```text
SKIPPED_NO_CHANGES: no changes; no new version or rotation.
```

### 3. Odtwarzanie wybranej wersji

```bash
sudo /opt/bso-secure-backup/.venv/bin/python \
  /opt/bso-secure-backup/backup.py restore \
  --output /var/lib/bso-secure-backup/backups \
  --project small \
  --version 1 \
  --target /var/lib/bso-secure-backup/restored-v1 \
  --keys /var/lib/bso-secure-backup/keys \
  --log /var/log/bso-secure-backup/backup.log
```

Katalog docelowy musi być nieistniejący albo pusty. Dane zostaną opublikowane w nim dopiero po pełnej weryfikacji.

## Polecenia i parametry CLI

Pomoc ogólna:

```bash
python backup.py --help
```

Pomoc dotycząca konkretnego polecenia:

```bash
python backup.py init-keys --help
python backup.py backup --help
python backup.py restore --help
```

### `init-keys`

Tworzy nowy komplet kluczy. Nie nadpisuje istniejących plików.

| Parametr | Wymagany | Znaczenie |
|---|:---:|---|
| `--keys PATH` | tak | Pusty lub nieistniejący katalog, w którym zostaną zapisane klucze. |
| `--log PATH` | nie | Plik logu. Domyślnie `backup.log` w bieżącym katalogu. |

### `backup`

Tworzy, sprawdza i publikuje nową wersję albo pomija operację, jeśli dane się nie zmieniły.

| Parametr | Wymagany | Znaczenie |
|---|:---:|---|
| `--source PATH` | tak | Katalog zawierający dane przeznaczone do ochrony. |
| `--output PATH` | tak | Główny katalog wszystkich projektów i ich wersji. Musi znajdować się poza źródłem i katalogiem kluczy. |
| `--keys PATH` | tak | Katalog zawierający `aes.key`, `private.key` i `public.key`. |
| `--keep N` | nie | Liczba najnowszych poprawnych wersji do zachowania. Domyślnie `3`, minimum `1`. |
| `--log PATH` | nie | Plik logu. Domyślnie `backup.log`. |

### `restore`

Odtwarza wybrany numer wersji konkretnego projektu.

| Parametr | Wymagany | Znaczenie |
|---|:---:|---|
| `--output PATH` | tak | Główny katalog archiwum użyty wcześniej podczas tworzenia kopii. |
| `--project NAME` | tak | Nazwa projektu, czyli nazwa katalogu źródłowego, np. `small`. |
| `--version N` | tak | Dodatni numer wersji do odtworzenia. |
| `--target PATH` | tak | Nieistniejący albo pusty katalog docelowy. |
| `--keys PATH` | tak | Katalog zawierający klucze właściwe dla kopii. |
| `--log PATH` | nie | Plik logu. Domyślnie `backup.log`. |

## Najważniejsze funkcje programu

Cała aplikacja znajduje się w `backup.py`. Najważniejsze funkcje to:

| Funkcja | Parametry | Odpowiedzialność |
|---|---|---|
| `manifest(folder)` | `folder` — katalog źródłowy | Zwraca słownik ścieżek, katalogów i SHA-256 plików. Odrzuca dowiązania i pliki specjalne. |
| `init_keys(folder)` | `folder` — katalog kluczy | Generuje AES-256 oraz parę Ed25519 i zapisuje je z prywatnymi uprawnieniami. |
| `read_key(folder, name)` | katalog i nazwa klucza | Sprawdza istnienie, właściciela i prawa klucza, a następnie odczytuje jego bajty. |
| `verify(version, keys)` | katalog wersji i katalog kluczy | Sprawdza SHA-256 oraz podpis Ed25519 przed odszyfrowaniem. |
| `backup(source, output, keys, keep=3)` | źródło, root kopii, klucze i limit | Realizuje cały przepływ tworzenia, autoweryfikacji, publikacji i rotacji kopii. |
| `restore(version, target, keys)` | katalog artefaktów, cel i klucze | Weryfikuje, odszyfrowuje, bezpiecznie rozpakowuje i sprawdza manifest. |
| `restore_project(output, project, number, target, keys)` | root, projekt, numer, cel i klucze | Odnajduje właściwy katalog wersji, a następnie wywołuje odtwarzanie. |
| `version_folders(project)` | katalog projektu | Zwraca katalogi wersji w kolejności liczbowej. |
| `configure_logger(path)` | ścieżka logu | Otwiera prywatny log tekstowy i konfiguruje zapis zdarzeń. |
| `secure_tree(folder)` | katalog danych | Ustawia 0700 dla katalogów i 0600 dla plików. |
| `require_root()` | brak | Na Linuksie odrzuca uruchomienie bez efektywnego UID 0. |
| `main(argv=None)` | opcjonalna lista argumentów | Buduje CLI, uruchamia wybrane polecenie i zamienia spodziewane wyjątki na czytelny komunikat. |

Funkcje można importować w testach, ale podstawowym i wspieranym sposobem korzystania z programu jest CLI.

## Uprawnienia i ochrona dostępu

Na Linuksie aplikacja:

- wymaga efektywnego UID 0,
- ustawia na czas działania `umask 077`,
- tworzy prywatne katalogi jako 0700,
- tworzy klucze, artefakty, log i odtworzone pliki jako 0600,
- sprawdza właściciela i prawa katalogu kluczy oraz plików kluczy,
- odrzuca dowiązania symboliczne użyte jako katalog kluczy, kopii lub plik logu.

Program nie zmienia automatycznie właściciela ani praw danych źródłowych. Administrator powinien zabezpieczyć je jawnie, np. dla demonstracyjnego zbioru:

```bash
sudo chown -R root:root test_data
sudo chmod -R go-rwx test_data
```

Kontrola praw:

```bash
sudo stat -c '%U:%G %a %n' keys keys/* logs/backup.log
sudo find backups -printf '%u:%g %m %p\n'
```

Samo działanie jako root nie chroni przed przejęciem konta root. W bardziej rozbudowanym systemie aplikacja powinna działać jako dedykowany użytkownik usługi o minimalnym zestawie uprawnień.

## Logowanie

Każde polecenie przyjmuje opcjonalne `--log`. Log zawiera między innymi:

- rozpoczęcie i wynik polecenia,
- rozpoczęcie i wynik weryfikacji,
- rozpoczęcie i wynik odtwarzania,
- pominięcie kopii bez zmian,
- numer utworzonej wersji,
- numery wersji usuniętych przez rotację,
- typ oraz opis kontrolowanego błędu.

Log nie zawiera materiału kluczowego ani odszyfrowanej treści plików. Jest zwykłym plikiem tekstowym przeznaczonym do demonstracji i diagnostyki, a nie dziennikiem odpornym na manipulację.

```bash
sudo tail -n 30 logs/backup.log
```

## Kody zakończenia

| Kod | Znaczenie |
|---:|---|
| `0` | Operacja zakończyła się sukcesem albo świadomie pominięto niezmienione dane. |
| `1` | Wystąpił kontrolowany błąd, np. brak klucza, błędny podpis, uszkodzenie kopii lub nieprawidłowa ścieżka. |

## Testy

Do testów deweloperskich nie jest wymagany root. Każdy przypadek używa własnego katalogu tymczasowego.

```bash
cd Secure_Backup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests -v
```

Testy obejmują między innymi:

- utworzenie i poprawne odtworzenie kopii,
- uszkodzenie jednego bitu szyfrogramu,
- brak klucza AES,
- zmianę podpisanych metadanych,
- nieudaną autoweryfikację,
- brak zmian,
- rotację wersji,
- niezależne projekty,
- wybór starszej wersji,
- numery wersji większe od 9,
- błędny projekt lub numer,
- konflikt źródeł o tej samej nazwie,
- wymaganie użytkownika root na Linuksie,
- zapis podstawowych zdarzeń w logu.

Aktualny wynik lokalny:

```text
14 passed
```

## Generator większego zestawu

`generate_data.py` tworzy deterministyczny zestaw 300–500 plików o łącznym rozmiarze do 200 MB.

```bash
python generate_data.py \
  --output test_data/generated \
  --count 300 \
  --mb 100 \
  --seed 2026
```

| Parametr | Domyślna wartość | Znaczenie |
|---|---:|---|
| `--output PATH` | brak | Pusty lub nieistniejący katalog docelowy. |
| `--count N` | `300` | Liczba plików w zakresie 300–500. |
| `--mb N` | `100` | Łączny rozmiar w MB, większy od 0 i nie większy niż 200. |
| `--seed N` | `2026` | Ziarno generatora zapewniające powtarzalną zawartość. |

Dużego zbioru nie należy dodawać do repozytorium.

## Struktura repozytorium

```text
Secure_Backup/
├── backup.py                  główna aplikacja CLI
├── generate_data.py           generator większego zestawu
├── requirements.txt           zależności Pythona
├── pytest.ini                 konfiguracja pytest
├── tests/
│   └── test_backup.py         testy automatyczne
├── test_data/small/           mały zestaw demonstracyjny
```

## Ograniczenia

- Archiwum i szyfrogram są przetwarzane w RAM.
- Kopie, klucze i log są lokalnymi plikami; projekt nie zapewnia kopii off-site ani magazynu HSM.
- Program nie obsługuje współbieżnego tworzenia kopii ani snapshotów systemu plików.
- Metadane są podpisane, ale niezaszyfrowane.
- Format nie jest kompatybilny z wcześniejszą, modułową wersją projektu.
- Bezpieczeństwo zależy od ochrony hosta, konta root, kluczy i całego środowiska Pythona.


## Dla kogo jest ten projekt

Projekt jest przeznaczony przede wszystkim dla studentów, osób uczących się bezpieczeństwa systemów Linux oraz prowadzących zajęcia lub demonstracje dotyczące ochrony kopii zapasowych.

Może pomóc w praktycznym zrozumieniu:

- różnicy między szyfrowaniem, sumą kontrolną i podpisem cyfrowym,
- znaczenia zarządzania kluczami i uprawnieniami systemu plików,
- wykrywania uszkodzeń przed odszyfrowaniem,
- bezpiecznego rozpakowywania archiwów,
- weryfikacji możliwości odtworzenia kopii,
- rotacji wersji i pomijania niezmienionych danych,
- ograniczeń prostego lokalnego systemu backupu.

Narzędzie może być używane jako baza do laboratoriów, demonstracji ataków na integralność oraz dalszych eksperymentów z keyringiem, kontem usługi, zewnętrznym magazynem kopii albo strumieniowym szyfrowaniem.


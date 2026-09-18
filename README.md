# Async Research Assistant — Topic 4

Wikipedia, arXiv və veb axtarışını **paralel** sorğulayan, nəticələri LLM ilə
sintez edib **istinadlı** cavab qaytaran CLI tətbiqi.

Verilmiş `ai/` modulu (mənbə fetcher-ləri + sintezator) dəyişdirilmədən
istifadə olunur; bu repo onun ətrafındakı **software engineering** qatıdır:
konfiqurasiya, paralel orkestrasiya, keş, retry, validasiya, loqlama, CLI,
testlər və Docker.

---

## 1. Sürətli başlanğıc

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# API açarı olmadan tam pipeline-ı yoxla (oflayn demo):
python -m researcher ask "What is photosynthesis?" --demo

# Testlər:
pytest -v
pytest --cov=researcher --cov-report=term-missing
```

Real işləmə üçün:

```bash
cp .env.example .env      # açarları doldur
python -m researcher ask "How do transformers handle long context windows?"
```

---

## 2. CLI

| Əmr | Nə edir |
|---|---|
| `ask "sual"` | Sual verir, istinadlı cavab çap edir |
| `benchmark "sual"` | Ardıcıl vs paralel yığımı müqayisə edir (keş sönülü) |
| `cache` / `cache --clear` / `cache --purge` | Keş statusu / tam təmizləmə / vaxtı keçmişləri silmə |
| `config` | Aktiv konfiqurasiyanı JSON kimi göstərir |

`ask` seçimləri:

```
--sources wiki,arxiv     yalnız seçilmiş mənbələr (wiki|arxiv|web)
--no-cache               keşi tamamilə bypass et
--demo                   oflayn rejim: açar və şəbəkə lazım deyil
--json                   nəticəni JSON kimi çap et (jq ilə işləyir)
--timings/--no-timings   vaxt ölçmələri
--timeout 5              mənbə başına timeout (san)
--max-results 5          mənbə başına nəticə sayı
--log-level DEBUG        loq səviyyəsi
```

Nümunə:

```bash
$ python -m researcher ask "What is photosynthesis?" --demo
Sual: What is photosynthesis?

Bu, demo rejimində yaradılmış nümunə cavabdır ... [1], [2], [3] ...

İstinadlar:
  [1] (wikipedia) Photosynthesis
      https://en.wikipedia.org/wiki/Photosynthesis
  [2] (arxiv) Attention Is All You Need
      https://arxiv.org/abs/1706.03762
  [3] (web) How plants make food
      https://example.com/plants

Vaxtlar:
  - wikipedia: 1 nəticə, 301 ms
  - arxiv: 1 nəticə, 451 ms
  - web: 1 nəticə, 251 ms
  fetch: 469 ms paralel / 1003 ms ardıcıl ekvivalent (×2.14)
  sintez: 1 ms
  cəmi:  507 ms
```

Çıxış kodları: `0` uğur · `1` icra xətası · `2` yanlış giriş · `130` dayandırıldı.
Loqlar **stderr**-ə, cavab **stdout**-a gedir — ona görə `--json | jq` işləyir.

---

## 3. Arxitektura

```
researcher/
├── config.py             env → tipli Settings (pydantic); os.environ yalnız burada oxunur
├── validation.py         sual validasiyası, çıxış sanitizasiyası, kanonik sorğu
├── models.py             FetchStatus, SourceFetchOutcome, FetchReport, ResearchResult
├── logging_setup.py      mərkəzi loglama (mətn və ya JSON), səviyyə env-dən
├── storage/
│   └── cache_store.py    CacheStore (ABC) + InMemory + FileSystem JSON + factory
├── services/
│   ├── retry.py          eksponensial backoff (jitter, "permanent" xətaları ayırır)
│   ├── cache.py          (source, sorğu) açarı, TTL, Source serializasiyası, hit/miss
│   └── ai_service.py     ai.* çağırışlarının YEGANƏ yeri (retry + log + to_thread)
├── concurrency/
│   └── orchestrator.py   asyncio.gather + mənbə başına timeout + degradasiya
├── core/
│   └── researcher.py     biznes məntiqi: validate → fetch → synthesize → nəticə
├── demo.py               oflayn demo (şablon LLM + hazır mənbələr)
└── cli.py                click əsaslı CLI
```

Axın:

```
CLI → Researcher.ask()
        ├─ validate_question()
        ├─ SourceOrchestrator.fetch_all()
        │     ├─ tək paylaşılan httpx.AsyncClient
        │     ├─ asyncio.gather(wiki, arxiv, web, return_exceptions=True)
        │     ├─ hər task üçün ayrıca asyncio.timeout()
        │     └─ hər mənbə üçün: keş → AIService.fetch() → retry → nəticə/xəta
        ├─ URL üzrə dedupe
        ├─ cavab keşi (sual + mənbə barmaq izi)
        ├─ AIService.synthesize() → asyncio.to_thread(ai.synthesize)
        └─ ResearchResult (cavab + istinadlar + vaxtlar + degradasiya qeydləri)
```

### Kontraktın qorunması

- `ai/` altında **heç bir fayl dəyişdirilməyib**.
- `tests/test_ai_smoke.py` toxunulmayıb; `tests/conftest.py`-a yalnız **əlavə**
  fixture-lar yazılıb (mövcud fixture-lar olduğu kimi qalıb).
- Provayder SDK-ları və mənbə API-ları biznes məntiqindən **birbaşa
  çağırılmır** — hər şey `researcher/services/ai_service.py` üzərindəndir.

---

## 4. Tələblərin qarşılığı

| Tələb | Harada | Necə |
|---|---|---|
| `config.py` | `researcher/config.py` | pydantic `Settings`, `from_env()`, `.env` oxuyucu, frozen model |
| Paralel orkestrasiya | `concurrency/orchestrator.py` | `asyncio.gather(..., return_exceptions=True)` |
| Mənbə başına timeout | həmin fayl, `_timeout()` | `asyncio.timeout()` (3.11+), fallback ilə |
| Graceful degradation | həmin fayl + `models.FetchReport` | xəta → `SourceFetchOutcome(status=ERROR/TIMEOUT)`, cavab qalan mənbələrdən; `notes()` istifadəçiyə göstərilir |
| Keş | `services/cache.py` + `storage/cache_store.py` | `(source, kanonik sorğu)` açarı, TTL, file/memory backend, `--no-cache` |
| CLI | `researcher/cli.py` | `ask`, `--sources`, `--no-cache`, `--json`, `benchmark`, `cache`, `config` |
| Citation tracking | `cli.render_result` + `models.ResearchResult` | `AnswerWithCitations` → nömrələnmiş istinadlar |
| Retry | `services/retry.py` | eksponensial backoff + jitter, konfiqurasiya xətalarında retry yoxdur |
| Validasiya | `validation.py` | boş/qısa/uzun sual rədd, control/ANSI simvol təmizliyi, çıxış sanitizasiyası |
| Loqlama | `logging_setup.py` | `logging`, `LOG_LEVEL`, opsional JSON format, stderr |
| Testlər | `tests/` | 94 test, **~90% coverage**, tamamilə oflayn |
| Dockerfile | `Dockerfile` | çoxqatlı, non-root user, keş üçün volume, import yoxlaması |
| README | bu fayl | quraşdırma, env, run, test, benchmark |

---

## 5. Paralel vs ardıcıl (benchmark)

```bash
python -m researcher benchmark "What is photosynthesis?" --repeat 3
# demo rejimində (şəbəkəsiz, simulyasiya olunmuş gecikmə ilə):
python -m researcher benchmark "What is photosynthesis?" --demo --repeat 3
```

Demo rejimində tipik nəticə (gecikmələr: wiki 300 ms, arXiv 450 ms, web 250 ms):

| Rejim | Wall-clock | İzah |
|---|---|---|
| Ardıcıl | ~1000 ms | `t_wiki + t_arxiv + t_web` |
| Paralel | ~450 ms | `max(t_wiki, t_arxiv, t_web)` |
| **Sürətlənmə** | **×2.2** | mənbə sayı artdıqca fərq böyüyür |

Hər `ask` çağırışı da bu ölçünü çap edir (`fetch: X ms paralel / Y ms ardıcıl
ekvivalent`), ona görə hesabatda real rəqəmləri birbaşa çıxışdan götürə bilərsən.

---

## 6. Testlər

```bash
pytest -v                                            # hamısı
pytest tests/test_ai_smoke.py -v                     # müəllimin smoke testləri
pytest --cov=researcher --cov-report=term-missing    # coverage
```

Testlər nəyi yoxlayır:

- `test_ai_smoke.py` — verilmiş modul (dəyişdirilməyib)
- `test_config_validation.py` — env parsing, alias-lar, sual validasiyası
- `test_cache.py` — TTL, korlanmış fayl, kanonik açar, hit/miss, backend factory
- `test_retry.py` — backoff pillələri, permanent xətalar, cancellation
- `test_orchestrator.py` — **paralellik ölçüsü**, timeout, degradasiya, dedupe, keş
- `test_researcher.py` — uçdan-uca axın, cavab keşi, sanitizasiya, JSON forma
- `test_ai_service.py` — dispatch, retry, `to_thread` sintez
- `test_cli.py` — bütün əmrlər, çıxış kodları, JSON çıxışı

Şəbəkə açılmır: `conftest.py`-dakı `no_network` fixture-ı avtomatik olaraq
real `httpx.AsyncClient` yaradılmasının qarşısını alır.

---

## 7. Docker

```bash
docker build -t research-assistant .
docker run --rm research-assistant                       # default: --demo
docker run --rm --env-file .env research-assistant \
    ask "What is photosynthesis?" --sources wiki,arxiv
docker run --rm -v research-cache:/data/cache --env-file .env research-assistant ask "..."
```

---

## 8. Konfiqurasiya

Bütün dəyişənlər `.env.example` faylında izahla verilib. Ən vaciblər:

| Dəyişən | Default | Təsir |
|---|---|---|
| `LLM_PROVIDER` / `LLM_MODEL` | anthropic / claude-sonnet-4-6 | sintez modeli |
| `WEB_SEARCH_PROVIDER` | tavily | tavily \| serper \| duckduckgo |
| `CACHE_BACKEND` / `CACHE_TTL_SECONDS` | file / 86400 | keş davranışı |
| `PER_SOURCE_TIMEOUT_SECONDS` | 10 | mənbə başına timeout |
| `RETRY_ATTEMPTS` | 3 | backoff cəhdləri |
| `LOG_LEVEL` | INFO | loq detallılığı |

---

## 9. Bilinən məhdudiyyətlər

- Keş fayl sistemindədir; çoxprosesli işdə `PostgreSQL` backend-i əlavə etmək
  üçün `CacheStore`-u implement edib `build_cache_store()`-a bir sətir əlavə
  etmək kifayətdir.
- Cavab keşi mənbə dəstinin barmaq izi ilə açarlanır: mənbələr dəyişəndə
  yenidən sintez olunur (istənilən davranış), amma bu, eyni sual üçün keş
  hit-ini nadir hala sala bilər.
- Web axtarış provayderi seçimi `ai/` modulundadır; SE qatı onu yalnız env ilə
  konfiqurasiya edir.

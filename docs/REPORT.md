# Hesabat — Topic 4: Async Research Assistant

**Tələbə:** Said Jabbarov · **Qrup:** 6424a3 · **Tarix:** _____

---

## 1. Problem və həll

İstifadəçi araşdırma sualı verir. Sistem eyni anda Wikipedia, arXiv və veb
axtarışı sorğulayır, uyğun parçaları toplayır və LLM ilə **istinadlı** vahid
cavab yaradır.

Verilmiş `ai/` modulu (async fetcher-lər, pluggable web search, sintezator)
dəyişdirilmədən istifadə edilib. Mənim işim onun ətrafındakı mühəndislik
qatıdır: konfiqurasiya, paralellik, keş, retry, validasiya, loqlama, CLI,
testlər, Docker.

## 2. Arxitektura qərarları

| Qərar | Alternativ | Niyə bu seçilib |
|---|---|---|
| `asyncio.gather(return_exceptions=True)` | `asyncio.wait` / ardıcıl | Bir mənbənin çökməsi digərlərini dayandırmır; nəticələr sıra ilə uyğunlaşdırıla bilir |
| Mənbə başına `asyncio.timeout()` | yalnız gather üzərində ümumi timeout | Yavaş Wikipedia arXiv-in vaxt büdcəsini yeməməlidir |
| Tək paylaşılan `httpx.AsyncClient` | hər fetcher öz client-ini yaratsın | TLS handshake 3 dəfə təkrarlanmır; kiçik sorğularda gözlə görünən fərq |
| `CacheStore` ABC + factory | birbaşa fayl I/O | Yeni backend (PostgreSQL) əlavə etmək üçün çağıran kod dəyişmir; `ai/providers` ilə eyni pattern |
| Kanonik sorğu açarı | xam sorğu | "WHAT IS X?" və "what is x" eyni keş qeydinə düşür |
| `ai.synthesize` üçün `asyncio.to_thread` | birbaşa çağırış | Bloklayan SDK çağırışı event loop-u dondurmur |
| Retry-də "permanent" xəta filtri | hər xətanı təkrarla | Açar yoxdursa 3 dəfə cəhd sadəcə 3.5 saniyə itkisidir |
| Loqlar stderr, cavab stdout | hamısı stdout | `--json | jq` və pipe-lar təmiz işləyir |

## 3. Paralel vs ardıcıl ölçmə

Əmr:

```bash
python -m researcher benchmark "What is photosynthesis?" --repeat 3
```

| Rejim | Run 1 | Run 2 | Run 3 | Orta |
|---|---|---|---|---|
| Ardıcıl | ___ ms | ___ ms | ___ ms | ___ ms |
| Paralel | ___ ms | ___ ms | ___ ms | ___ ms |
| Sürətlənmə | | | | **×___** |

> Yuxarıdakı cədvəli real çıxışla doldur. Nəzəri gözlənti:
> ardıcıl = `t₁+t₂+t₃`, paralel = `max(t₁,t₂,t₃)`, yəni bənzər gecikməli
> üç mənbə üçün sürətlənmə ×2–3 aralığında olur.

Mənbə başına vaxtlar hər `ask` çağırışında da loqlanır:

```
fetch: 469 ms paralel / 1003 ms ardıcıl ekvivalent (×2.14)
```

## 4. Keşin təsiri

| Ssenari | Vaxt | İzah |
|---|---|---|
| İlk sorğu (soyuq keş) | ___ ms | şəbəkə + LLM |
| Eyni sual (isti keş) | ___ ms | mənbələr keşdən, cavab keşdən |
| `--no-cache` | ___ ms | keş tamamilə bypass |

## 5. Xəta ssenariləri

| Ssenari | Gözlənilən davranış | Test |
|---|---|---|
| arXiv çökür | Cavab qalan 2 mənbədən, qeyd əlavə olunur | `test_failing_source_degrades_gracefully` |
| Bir mənbə asılıb qalır | Timeout, digərləri gözləmir | `test_slow_source_times_out_without_blocking_others` |
| Bütün mənbələr çökür | `NoSourcesError`, exit kodu 1 | `test_ask_raises_when_every_source_fails` |
| Keçici şəbəkə xətası | Backoff ilə təkrar cəhd | `test_fetch_retries_transient_provider_errors` |
| API açarı yoxdur | Dərhal xəta, təkrar cəhd yox | `test_fetch_does_not_retry_missing_api_key` |
| Boş/çox uzun sual | Validasiya xətası, exit kodu 2 | `test_validate_question_*` |
| Korlanmış keş faylı | Miss kimi qəbul edilir, silinir | `test_file_store_survives_corrupt_file` |

## 6. Test və coverage

```bash
pytest --cov=researcher --cov-report=term-missing
```

- Ümumi test sayı: ___
- Coverage: ___% (tələb: ≥60%)
- Bütün testlər oflayn işləyir (şəbəkə çağırışı yoxdur).

## 7. Nə öyrəndim / növbəti addımlar

- ...
- ...

Növbəti addımlar: PostgreSQL keş backend-i, FastAPI interfeysi, mənbə üzrə
çəkiləndirmə (origin-based weighting), sorğu genişləndirmə (query expansion).

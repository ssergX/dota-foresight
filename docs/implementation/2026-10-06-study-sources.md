# Учебные матчи: работающий источник OpenDota

`src/dota_coach/ingest/study_sources.py` реализует read-only адаптер. Он использует только GET, не запрашивает парсинг и не обновляет профиль игрока. Основные API подтверждены [официальной документацией OpenDota](https://docs.opendota.com/); nullable `replay_url`, provider `patch` и `rank_tier` сверены с [типами самого OpenDota](https://github.com/odota/core/blob/master/global.d.ts). Дополнительно проведён фактический сетевой smoke.

## Интеграция

```python
from pathlib import Path
from dota_coach.ingest.study_sources import OpenDotaStudySource

source = OpenDotaStudySource(Path("cache/study-sources"))
example = source.fetch_match_source(
    9030822324, 145, account_id=904131336,
    probe_replay=True, check_pro=True,
)
selection = source.discover(
    145, role="position_1", patch="opendota_patch_id:60",
    limit=3, max_fetches=8,
)
```

`fetch_match_source` проверяет точное совпадение match ID, hero ID и, при запросе, account ID. Он возвращает `SourcedStudyExample`: `study`, `account_id`, `player_slot`, `association_evidence_ref`, `role_estimate`, `expertise_class`, `expertise_basis`, `rank_tier`, `patch_id`, `replay_probe`, `receipts`, `teaching_status`, `difference_codes`. `discover` возвращает `StudyDiscovery`: `status`, `examples`, `exclusions`, `receipts`, `reason_codes`, `limitations`. Поиск ограничен `max_fetches≤30`; default — 8 карточек. Можно искать историю конкретного account или последние записи `/proMatches`.

`discover(..., exclude_match_ids=(target_match_id,))` исключает целевой матч до расходования candidate fetch budget. Два реальных внешних примера hero145 уже сохранены в `out/study-live/discovery.json`: 9031046793 и 9030693809, оба patchID60/position_1 estimated/registered_pro, с TF1003с и719с соответственно.

`save_study_discovery(discovery, path)` сохраняет captured result атомарно. `load_study_discovery(path)` offline реконструирует immutable DTO и проверяет canonical hash, source routes, actual match/hero/account/player_slot, recomputed role, pro registry/rank, patch и существование episode pointers. Source timestamp сохраняется. Probe получает limitation `captured_probe_not_rechecked_current_availability_unknown`: новый сетевой запрос не имитируется, текущая доступность не подтверждена. Loader проверяет внутреннюю целостность, не аутентичность сервера и не decision quality; локальный файл не может выдать criterion grant.

Карточка с `teaching_status=source_backed_comparison` имеет конкретные episode refs, задачу просмотра и доступный заголовок реплея. `metadata_only` означает, что имеются проверенные метаданные, но просмотр учебного реплея сейчас не подтверждён. UI должен сохранять это различие. `sourced_examples` не означает аттестованное качество решений автора матча.

Источники представлены immutable fetch receipt: официальный URL, время реального получения, SHA-256 canonical JSON, неизменяемая JSON-строка. `receipt.data` всегда возвращает новую копию. `StudyMatch.sources[0]` содержит публичную ссылку на матч, а его hash относится к API JSON, связанному через receipt; это не hash HTML страницы. Кэш повторно проверяет schema, URL, timestamp, возраст, digest и payload. Неполные/подменённые/просроченные записи перечитываются; публикация кэша атомарна после валидации. TTL по умолчанию — 1 час, rate interval — 1,1 с; ошибки сети/HTTP не создают фиктивный результат.

## Семантика контекста

* `registered_pro` требует совпадения account ID с фактически полученным `/proPlayers`. Имя в карточке и участие матча в списке proMatches сами по себе не повышают игрока до pro.
* `high_rank` основан на nullable `rank_tier≥80` в карточке. Это медаль провайдера; числовой MMR не выводится, `StudyMatch.expertise_status` остаётся unknown без профессионального источника.
* `role_estimate.confidence=estimated` открыто отделяет оценку позиции от проверенной командной роли. Метод использует lane_role и last hits пары игроков на линии; roaming/недостаточный/неоднозначный контекст даёт unknown. Данные всего матча используются только для описательного подбора, не для оценки решений до эпизода.
* `opendota_patch_id:60` — точный provider identifier, без вымышленного отображения на название патча и без допуска mechanics criterion.
* Teamfight source pointers задают места просмотра. Они не устанавливают границу решения и не доказывают ошибку. Задание просит разделить доступную информацию, альтернативы и последующий результат.
* Наличие replay URL не означает доступность. Проверяется ограниченный GET Range заголовка на разрешённом Valve hostname и URL конкретного матча. 404/410 означает unavailable, сетевой отказ/403/неверный binary header — unknown. `available` подтверждает только чтение binary prefix; полнота файла, разбор и POV не аттестованы.
* Импорт произвольного локального каталога через `learning.portfolio.load_study_catalog` по-прежнему остаётся untrusted. JSON не может сам повысить verified/pro/real/replay status.

## Проверенный результат

Артефакт: `out/study-live/study-source.json`; краткий receipt: `out/study-live/smoke-receipt.json`.

Реальный матч **9030822324**, герой **145**, account **904131336**: API подтвердил association; account присутствует в полученном proPlayers; patch ID **60**; позиция **position_1, estimated**; первый отмеченный teamfight начинается на **413 с**. Binary prefix Valve replay был прочитан, SHA-256 prefix сохранён. Эти данные не доказывают качество решений и не валидируют реактивный evaluator.

`tests/test_study_sources.py`: **37 passed**. Вместе с `tests/test_learning_modules.py` и `tests/test_ward_review.py`: **79 passed**. Проверены schema/actual IDs, подмена и expiry кэша, атомарность, source hashing, immutability, hero/account association, role/rank distinction, bounded discovery, target exclusion, offline captured-source binding, отсутствие POST, unknown для недоступного replay и запрет произвольных replay URL.

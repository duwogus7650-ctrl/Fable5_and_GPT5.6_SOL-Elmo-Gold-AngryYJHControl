# Expert Summary · Documented Transaction Map v0.1

## 범위와 판정

이 기능은 설치된 EAS III Gold 도움말의 Expert Tuning `Summary` 화면을
읽기 전용 정적 transaction map으로 정리한다. 실제 EAS Summary 상태,
드라이브 flash/RAM, 로컬 파일, 설계 산출물 또는 motor database를 읽거나
변경하지 않는다.

- model id: `expert_summary_documented_transaction_map_v0_1`
- authority: `DOCUMENTED_SUMMARY_TRANSACTION_MAP_ONLY`
- model status: `PARTIAL_NEED_DATA`
- fidelity: `DOCUMENTED_STATIC_REFERENCE`
- canonical shape: **3 sections × 4 rows = 12 rows**
- inspect operation:
  `tuning.expert.summary.evidence.inspect` (`LOCAL_UI / PARTIAL`)

실제 변경은 다음 네 operation으로 분리돼 모두 menu-disabled
`NEED_DATA`다.

| Operation | Risk | 실제 효과 |
|---|---|---|
| `tuning.expert.summary.drive_persist` | `PERSISTENT_WRITE` | 선택 tuning parameter를 drive flash에 SV |
| `tuning.expert.summary.parameter_export` | `LOCAL_FILE` + 문서상 drive read | drive parameter를 읽어 local parameter file로 export |
| `tuning.expert.summary.design_export` | `LOCAL_FILE` | identified plants/controllers를 local artifact로 export |
| `tuning.expert.summary.database_import` | `LOCAL_FILE` + local DB mutation | 선택 motor database에 tuning-session motor data import |

`LOCAL_FILE` risk badge는 실제 drive read나 DB mutation이 낮은 위험이라는
뜻이 아니다. 현재 catalog enum이 복합 risk를 표현하지 못하므로 summary와
정적 map에서 복합 authority를 명시하며 실행은 계속 잠근다.

## 고정 zero-I/O 경계

`STATIC DOCUMENT MAP ONLY · DOCUMENTED SUMMARY TRANSACTION MAP ·
PARTIAL / NEED-DATA · NOT CURRENT EAS SUMMARY STATE ·
NOT CURRENT DRIVE STATE · NOT CURRENT FILE STATE ·
NOT CURRENT MOTOR DATABASE STATE · NOT PROOF OF SAVED DATA ·
NO DRIVE READ/UPLOAD · NO SV/DRIVE SAVE · NO FILE DIALOG ·
NO FILE/DESIGN EXPORT · NO DATABASE IMPORT/MUTATION ·
NO SAVE/APPLY · NO COMMAND GENERATION · NO ENERGIZATION/MOTION ·
NO DRIVE I/O`

`can_inspect`만 `True`다. drive/file/database 관찰, checkbox 선택, path
선택, file dialog, drive upload/SV, file/design save, DB import/mutation,
command/write/Apply/persist, energization/motion, saved/complete/safety
판정은 모두 `False`다.

모델 import, snapshot 생성, strict section lookup과 UI section 전환은
file, socket, process, worker, dialog, database 또는 drive I/O를 만들지
않는다.

## 설치 문서에서 확인한 Summary 계약

Gold UM `Drive Setup and Motion Activities.htm` §8.2.2 steps 80–85는
Verification–Bode 다음에 Summary를 표시하고 다음을 설명한다.

1. `Save Parameters in Drive (SV)` checkbox
2. `Upload Parameters from Drive` checkbox와 parameter file path
3. `Save Design Plants` checkbox와 design folder path
4. 선택적인 `Import to DB…`
5. 선택 항목을 실행하는 단일 `Save`

따라서 Summary는 단순 결과 요약 화면이 아니라 서로 다른 권한을 한 번의
Save에 묶을 수 있는 종료 transaction이다.

설치된 before-save image에는 세 checkbox, 두 destination field/browse
control, `Import to DB…`, `Save`가 표시된다. after-save example에는
`3810 of 3810 parameters`, `VelocityPlants`, `CurrentPlants`,
`Completed Successfully`가 표시된다. 이 값은 문서 예시이며 현재 target,
file inventory, hash, readback 또는 성공 결과가 아니다.

## 3 × 4 고정 문서맵

모든 행은
`document: inspect-only · app: inspect-only`다.

### 1. Recommended Actions

| Key | Documented control | Authority |
|---|---|---|
| `save_parameters_in_drive` | Save Parameters in Drive (SV) | `PERSISTENT_WRITE` |
| `upload_parameters_from_drive` | Upload Parameters from Drive | `DRIVE_READ + LOCAL_FILE` |
| `save_design_plants` | Save Design Plants | `LOCAL_FILE` |
| `import_to_motor_database` | Import to DB… | `LOCAL_DATABASE_MUTATION` |

### 2. Save Transaction

| Key | Documented group | Boundary |
|---|---|---|
| `parameter_file_path` | Parameter File Path | screenshot example; current path unknown |
| `design_folder_path` | Design Folder Path | screenshot example; current path unknown |
| `save_commit` | Save (combined commit) | multi-authority atomicity NEED-DATA |
| `completion_log` | Completion Log | documented example; not current result |

### 3. Authority Split

| Key | Separated authority | Execution status |
|---|---|---|
| `drive_flash_persistence` | SV + exact flash set/readback/power-cycle/rollback | `NEED_DATA / UNIMPLEMENTED` |
| `drive_parameter_export` | bounded drive snapshot + local atomic file | `NEED_DATA / UNIMPLEMENTED` |
| `design_artifact_export` | source identity + schema/inventory + local files | `NEED_DATA / UNIMPLEMENTED` |
| `motor_database_mutation` | DB identity/backup/schema/duplicate/transaction | `NEED_DATA / UNIMPLEMENTED` |

## 보존한 문서 ambiguity

1. `UPLOAD_DIRECTION` — UI는 Upload from Drive라고 쓰고 prose는 file에
   저장한다고 설명하지만 exact snapshot/protocol/file schema는 이
   section에서 확정되지 않는다.
2. `SAVE_COMMIT_LABEL` — main Expert 절차는 `Save`, 일부 gantry 절차는 같은
   Summary checkbox 뒤 `Apply`를 설명한다. target-specific transaction
   semantics가 필요하다.
3. `DESIGN_ARTIFACT_SCHEMA` — prose는 모든 identified plants/controllers를
   말하고 example log는 VelocityPlants/CurrentPlants를 말하지만 전체
   inventory, extension, schema와 version은 확정되지 않는다.

## 지속 경고와 누락 증거

항상 보존하는 warning category:

- `DOCUMENTED_MAP_ONLY`
- `NO_RUNTIME_IO`
- `MULTI_AUTHORITY_TRANSACTION`
- `SV_POWER_CYCLE`
- `PARTIAL_FAILURE`
- `SCREENSHOT_NOT_CURRENT_STATE`

실제 실행 전에 필요한 evidence:

- exact target/session identity
- exact pre-save changed-parameter/design/DB snapshot
- destination path, permission, collision, free-space와 atomic-write contract
- parameter/design file schema, version, inventory와 independent parser
- DB identity/schema/backup/duplicate/update/transaction contract
- selected-action ordering, atomicity와 partial-failure recovery
- SV readback/power-cycle, exported file hash/content, DB post-write verification
- 모든 부분 완료 상태의 rollback/recovery

이 evidence가 없으므로 actual Summary Save는 **NEED-DATA / NO-GO**다.

## Source identity

| Key | Installed source | SHA-256 |
|---|---|---|
| `drive_setup_html` | `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\EAS_II_SimplIQ_Gold_UM\Drive Setup and Motion Activities.htm` | `BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE` |
| `summary_before_image` | `...\Drive Setup and Motion Activities_46.png` | `2C39359565D75F5886CB44C4D772762BD30129D912212A94A5A15E53E7D48B21` |
| `summary_after_image` | `...\Drive Setup and Motion Activities_47.png` | `5D26C4670ECF1ABD94E9F031B873459081D1E790629B0D96F4441043CF8E14A4` |

HTML lines 1447–1460과 두 image를 직접 읽었고 위 세 SHA-256을 설치
source에서 재계산했다. source identity는 모델에 상수로 동결되며 runtime
UI가 설치 파일을 다시 읽지 않는다.

## 현재 검증 범위

- RED: model import 부재, operation ID 부재, UI `summary` step 부재를 각각
  실패로 확인한 뒤 구현
- Summary model/catalog/UI와 기존 Expert/connection/persistence/safety
  영향범위: **276 passed in 62.86s**
- immutable singleton, exact 3 × 4 row order, strict lookup
- fresh import/build/lookup file·socket·subprocess I/O poison
- actual Save/SV/file dialog/export/DB mutation control widget **0**
- 세 테마 1366×820 geometry, table contrast/header width,
  horizontal-scroll 0
- source SHA-256 **3/3 match**
- 전체 repository suite: **1587 passed in 266.87s**, numeric exit **0**
- Python 3.14, 1366×820 새 제어창 runtime:
  `OFFLINE · READ ONLY`, 열 번째 `SUMMARY DOC MAP`, 3 sections ×
  **4 documented groups**, Summary page action/edit widget **0**
- runtime에서 Connect, drive read/upload, Summary Save, SV, file dialog,
  file/design export, DB import/mutation, Apply, energization 또는 motion은
  실행하지 않음

위 GREEN은 `DOCUMENTED_SUMMARY_TRANSACTION_MAP_ONLY`인 로컬 static
catalog/UI에만 적용된다. EAS Summary parity, 실제 SV/upload/file/design/DB
transaction, 저장 성공, 복구 가능성 또는 안전성은 검증하지 않았다.

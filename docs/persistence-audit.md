# P1/P2/Motor persistence UNKNOWN audit 계약

## 목적과 범위

`SV`는 비휘발 파라미터를 RAM에서 flash로 저장하며 통신을 수백 ms 중단할 수 있다. 따라서
명령을 보낸 뒤 응답을 잃으면 저장 성공과 실패를 응답만으로 구분할 수 없다. 이 기능은 그
상태를 추측하지 않고, 앱 재시작 뒤에도 쓰기 권한을 잠근 채 전원 재인가 후 실제 P1/P2 게인
또는 Motor profile을 읽어서 분류한다.

범위는 P1 `KP[1]/KI[1]`, P2 `KP[2]/KI[2]/KP[3]`, Motor
`PL[1]/CL[1]/VH[2]/CA[19]/CA[28]` 프로파일이다. 결과는 whole-drive 설정,
커뮤테이션 유효각, 폐루프 안정성, motion safety를 증명하지 않는다. Feedback direct save와
write-only Encoder Maintenance `TW[18..20]`은 이 계약의 대상이 아니다.

## Motor RAM transaction

Motor 저장은 단순 assignment 뒤 `SV`가 아니다.

1. 동일 identity/session에서 target, 안전 상태와 환산 의존값을 읽고 타입·범위·관계를 검증한다.
   `MO=SO=VX=MF=0`, `PS=-2/-1`, `VH[2]≤2^31-1`, `CL[1]<MC`, `PL[1]≤MC`를 요구한다.
2. 첫 RAM assignment 전에 original/desired profile과 연결 문맥을 durable WAL에 기록한다. WAL 기록
   직후 전체 Motor/안전 snapshot이 사전검사 값과 정확히 같은지 다시 확인한다.
3. 각 forward assignment 직전과 각 rollback assignment 직전에 위 안전 상태를 다시 조회한다.
   변경값을 RAM에 적용하고 대상 전체를 되읽는다. 일부 실패, timeout 또는 불일치는 `SV`를
   금지하고 원값 rollback과 전체 되읽기를 한 번 수행한다.
4. rollback이 완전히 확인되지 않으면 active UNKNOWN을 유지한다. 확인되면 `SV` 없이 종료한다.
5. applied profile 전체가 확인된 같은 request만 record ID가 일치하는 `SV` authority를 한 번 소비할 수 있다.
   `PERSISTING` 원장 fsync 뒤 전체 profile/안전 snapshot과 마지막 안전 전용 조회를 다시 통과해야 한다.
   이 경계에서 상태가 바뀌면 rollback authority를 되살리지 않고 UNKNOWN으로 잠그며 `SV`는 보내지 않는다.
   응답 유실, session 변경, closeout 실패에는 자동 rollback이나 `SV` 재시도를 하지 않는다.

GUI는 요청을 queue에 넣는 순간 Motor 저장 버튼을 잠그고 과거 P1/P2 결과의 Apply 권한을 폐기한다.
연결/Motor 변경마다 단조 증가 세대 토큰을 발급하며, 현재 worker·현재 dispatch·같은 세대의
result/trial/verification만 Apply·Verify·Save 권한이 된다. Motor 저장과 튜닝 dispatch는 양방향으로
동시에 시작할 수 없다. 재연결도 이전 연결 세대의 결과와 지연된 worker 신호를 계승하지 않는다.
현재 worker의 결과 뒤에도 연결이 유효하고 persistence lock이 없을 때만 저장 버튼을 다시 연다.

이 재조회는 직렬 명령 사이의 가장 가까운 소프트웨어 경계다. 마지막 `MF` 응답 뒤 다른 EAS,
CAN/EtherCAT master 또는 별도 프로세스가 drive를 enable하는 것을 원자적으로 막지는 못한다.
따라서 실기 저장 중 외부 제어기의 배타적 제어권 확보는 여전히 `NEED-DATA` 현장 게이트다.

## SV 전 write-ahead 순서

1. 같은 연결 세션의 해시된 `SN[4]`, 정확한 `VR/VP/VB`, connection epoch를 확인한다.
2. record 종류별 original/applied 전체가 exact register set과 type/range 계약을 만족하는지 검증한다.
3. P1/P2는 0.1% 판정 허용오차, Motor는 정수/config 포함 exact 비교로 original/applied가
   구별되는지 확인한다. 구별되지 않으면 no-op으로 보고 `SV` 준비 자체를 거부한다.
4. P1/P2는 `SV` 직전 `PERSISTING`을 만들고, Motor는 첫 RAM 쓰기 전 이미 만든
   `RAM_APPLYING` record를 전체 applied readback 뒤 `PERSISTING`으로 전이한다. 모든 상태 변경은
   interprocess lock 아래 temp write → flush/fsync → atomic replace → readback 검증한다.
   여러 앱 인스턴스의 load-modify-commit도 직렬화하므로 다른 drive incident를 덮어쓰지 않는다.
5. 위 단계가 성공한 같은 identity·connection epoch 및 정확히 같은 record ID에서만 `SV`를 한 번 실행한다.
6. 같은 호출에서 실제 성공 응답을 받은 attempt만 resolved archive로 닫는다. 응답 유실이나 archive 실패는 active UNKNOWN으로 남긴다.

원장은 schema와 payload의 SHA-256을 검증한다. JSON, schema, checksum, record 의미가 손상되면
자동 삭제하거나 빈 상태로 대체하지 않고 전역 fail-closed한다.
첫 mutation 때 만든 sibling `.lock`은 초기화 sentinel로 계속 보존한다. 이후 JSON만 사라지면
새 앱도 빈 원장으로 보지 않고 `LedgerIntegrityError`로 잠근다.

안전 원장은 checkout 내부나 OneDrive가 아니라 사용자 로컬 고정 경로
`%LOCALAPPDATA%\AngryYJHControl\safety\persistence_unknown.json`에 둔다. 따라서 같은 최신 앱의
다른 checkout도 한 원장을 사용한다. 이 계약을 모르는 구버전/원본 앱은 이 잠금을 집행하지
못하므로 UNKNOWN이 있는 동안 제어용으로 실행하면 안 된다.

## 전원 재인가 후 query-only audit

사용자가 UNKNOWN 발생 뒤 드라이브를 냉간 `OFF → ON` 했거나 flash가 다시 로드되는 동등한
reset을 완료했다고 명시적으로 확인해야 한다. USB 재연결만으로는 reset을 증명하지 못한다.

Audit은 `SN[4]`, `VR`, `VP`, `VB`, `MO`, `SO`, `VX`, `PS`, `MF`와 해당 record profile을
두 번 조회한다. 동일 identity, 정확한 software context, incident와 다른 connection epoch,
`MO=0`, `SO=0`, `VX=0`, 유효한 disabled `PS`, 안정된 두 snapshot을 모두 요구한다.
`SV`, `LD`, `RS`, assignment, enable, motion 명령은 보내지 않는다.

- `RESOLVED_APPLIED_PROFILE`: 전원 재인가 뒤 durable 값이 applied profile과 일치한다.
- `RESOLVED_ORIGINAL_PROFILE`: 전원 재인가 뒤 durable 값이 original RAM profile과 일치한다.
- `UNRESOLVED_NO_DISTINGUISHING_CHANGE`: 구버전/외부 생성 record에서 두 profile이 tolerance 안에서
  같으면 추측하지 않는다. 새 attempt는 이 상태가 생기기 전에 준비 단계에서 거부된다.
- identity/software/session/readback 불일치 또는 mixed profile: 잠금을 유지한다.

Applied/original 일치는 현재 durable profile의 관측이다. ambiguous `SV`가 인과적으로 성공 또는
실패했다는 주장이 아니다. Audit 완료 뒤에도 commutation signature와 motion authority는 새로
검증해야 한다.

잠금을 해제한 resolved record에는 명시적 reset attestation, 새 audit epoch, 해시된 identity,
정확한 VR/VP/VB, 두 번의 `MO/SO/VX/PS/MF + record profile` snapshot과 evidence SHA-256을 함께
보존한다. raw serial은 기록하지 않으며, 재로딩 때 snapshot 안정성·disabled 상태·profile 일치와
내부/외부 checksum을 다시 검증한다.

## 근거와 검증

- 로컬 Gold Line Command Reference: `SV` RAM→flash와 통신 중단 가능성, `LD` flash→RAM의
  상태 변경 성격, `RS`가 durability reset이 아님.
- 순수 원장/판정 테스트: `tests/test_persistence_audit.py`.
- 전송/재시작/identity/명령 음성 대조: `tests/test_elmo_persistence_lifecycle.py`.
- Worker/UI 중앙 잠금: `tests/test_main_persistence_ui.py`.

## Feedback direct save 잠금

Feedback 화면의 센서 목록과 필드 배치는 read/preview capability다. 이것만으로 write authority를
만들지 않는다. 센서/펌웨어별 exact command, type/range, `CA[41]` 재기입 부작용, 원본/적용
snapshot과 rollback 순서를 고정한 versioned registry가 마련될 때까지 Feedback assignment와
`SV`는 UI 버튼과 dispatch handler 양쪽에서 fail-closed한다. Encoder Maintenance는 encoder
datum 자체를 바꾸며 별도 `SV`가 필요 없는 독립 작업이므로 일반 profile ledger에 섞지 않는다.

현재 검증 수준은 OFFLINE이다. 실제 응답 유실 + 감독하 냉간 전원 재인가 현장 시험 전에는
LIVE라고 표시하지 않는다.

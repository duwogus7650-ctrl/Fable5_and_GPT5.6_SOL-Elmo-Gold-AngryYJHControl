# Gold Drive / Feedback 검증 매트릭스

기준일: 2026-07-17<br>
활성 구현 범위: [`current-scope-handoff.md`](current-scope-handoff.md)

## 원칙

`Gold`는 공통 software/firmware 계열을 뜻하지만 동일 전력단, 입력 전원, feedback connector, I/O,
통신, 보호와 tuning setting을 보장하지 않는다. 같은 제품명에도 current/voltage/network/feedback variant가
있으므로 모델명만으로 프로그램 호환을 승인하지 않는다.

각 drive + motor + feedback 조합은 별도 capability profile과 evidence identity를 가져야 한다. 이전 장비의
`CL/PL`, gain, commutation, encoder scale, direction, limit, brake, STO 설정을 새 장비에 복사하지 않는다.

## 계획 매트릭스

| 순서 | Drive | Motor feedback / commutation | 현재 판정 | 먼저 필요한 증거 |
|---:|---|---|---|---|
| 1 | 현재 Gold Twitter exact unit | EnDat 2.2 | 활성 기준선 · LIVE 재검증 전 | exact identity, FW/PAL, CA routing/scale, current limits, 최신 Quick/finite-PTP transcript |
| 2 | 같은 Gold Twitter | incremental encoder | CONDITIONAL / NEED-DATA | counts/rev/index, startup commutation source, direction, noise/filter, loss/fault behavior |
| 3 | 같은 Gold Twitter | Hall-only | CONDITIONAL / NEED-DATA | Hall sequence/polarity/electrical angle, 허용 control mode, 저해상도 position 성능 한계 |
| 4 | 같은 Gold Twitter | Hall commutation + incremental precision | CONDITIONAL / NEED-DATA | 두 feedback의 역할 분리, phasing, scale, switch/startup behavior, fault fallback |
| 5 | exact Gold Drum 모델 TBD | 위와 동일한 모터들을 순차 반복 | CONDITIONAL / NEED-DATA | exact product/part number, 전원·전류·냉각·I/O·feedback·STO·통신 차이와 새 profile |

`Gold Drum`은 단일 사양명으로 취급하지 않는다. classic/360/550/HV 등 실제 part number와 전력 사양이
확정되기 전에는 코드 capability나 일정 승인을 하지 않는다.

## 새 조합 admission 체크리스트

1. drive exact product name, part number, serial hash, firmware, PAL, boot, transport
2. DC/AC input, continuous/peak current, current convention, voltage, cooling과 load restraint
3. motor phase order, poles/pole-pairs, phase/line 및 RMS/peak convention
4. primary feedback, commutation feedback, auxiliary feedback의 connector/routing
5. counts/rev, multi-turn 범위, index/Hall sequence, electrical/mechanical direction과 zero 의미
6. FLS/RLS/STOP, brake, STO/E-stop wiring, polarity와 reaction evidence
7. live command support와 readback semantics: `UM/MO/SO/MF/SR/CA/KP/KI/CL/PL/VH/VL/XM`
8. 기능별 first-assignment durable WAL, full readback, rollback, `UNKNOWN`, 별도 `SV`와 cold audit.
   Gain trial은 P2_LIMITS와 공존하는 pre-assignment WAL이 구현되기 전까지 admission하지 않는다.

하나라도 빠지면 기존 profile을 적용하지 않고 `NEED-DATA`로 유지한다.

## 조합별 검증 순서

1. 전원 차단 상태의 배선·nameplate·part-number 기록
2. query-only identity/feedback routing/range 수집
3. disable·정지·무전류 closeout oracle 확인
4. sensor direction/scale/index 또는 Hall sequence의 제한 에너지 검증
5. Quick Tuning P1 후보 → commutation signature → P2 후보
6. 현재 설치 P2 게인 Verify. Gain Apply/Save는 durable pre-assignment trial WAL이 구현된 미래의
   별도 admission 단계이며 현재 production 순서에는 포함하지 않는다.
7. finite PTP는 물리 envelope와 독립 stop evidence 뒤 최저 에너지부터
8. abort, sensor fault, comms loss, reconnect, power cycle, durability

한 조합의 GREEN을 다른 조합으로 전파하지 않는다.

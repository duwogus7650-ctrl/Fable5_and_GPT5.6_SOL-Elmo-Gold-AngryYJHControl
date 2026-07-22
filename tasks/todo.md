# TODO

근거·측정값·판단은 [`tasks/status.md`](status.md)에, 실패 경위는
[`tasks/failure-ledger.md`](failure-ledger.md)에 있다. 여기는 **다음에 할 일**만 둔다.

업데이트: 2026-07-22

---

## 오프라인 (실기 불필요)

- [ ] **커뮤 정밀 δ 보정의 트랜잭션 차단 수정** — status §4.1 · btw-030 · **HIGH**
      `commutation_id.py:649`의 `_ca7_write_verified`가 persistence로 막히면
      RED 대신 **YELLOW 정직 강등**(enable-watch 판정만 주장). '기준 없음' 경로가
      이미 쓰는 방식과 동일하게. 이걸 고치면 원버튼 체인이 전원 재인가 후에도
      ①에서 안 멈춘다.
- [ ] **조그 루프 건강 트레이스** — status §4.3 · **HIGH**
      재스탬프 실제 간격 · 읽기 타임아웃 · 데드만 놓침 횟수를 조그 결과 증거에
      기록. "3550 rpm 멈칫"이 통신 경합인지 다른 것인지 다음 발생 때 판별된다.
      (같은 방법이 롤백 정지대기에서 한 번에 답을 냈다 — status §4.2)
- [ ] **Session Zero 순서 안내** — status §4.4 · btw-031 · MEDIUM
      최소안: Apply 거부 메시지에 "Session Zero → Apply" 순서 명시.
      확장안: 체인에 Session Zero를 Apply 앞 단계로 편입(축 위치는 운영자가
      정하므로 승인 창 고지 필요) — 사용자 결정 대기.
- [ ] **체인에 Verify 편입 여부** — status §4.5 · btw-026 후속 · LOW
      실제 회전이 늘어나므로 승인 창 반영 필요 — 사용자 결정 대기.
- [ ] **조그 결과에 `_build_rev` 스탬프** — LOW
      `_dump_jog_result`만 `_result_payload`를 안 쓴다(다른 3개는 적용됨).
- [ ] **원버튼 체인 독립 리뷰** — status §5 마지막 항목
      작성/검토 분리를 못 지켰다. 코드 리뷰 패스 1회.

## 실기 필요

- [ ] **3600 rpm 지령 통과 확인** — `161b5c6`의 천장 여유 수정 검증점.
      오늘은 3550으로 우회했다.
- [ ] **P2_LIMITS 롤백 정지 증명 판별** — status §4.2
      트레이스가 이미 들어가 있으므로 **다음 발생 시 자동 기록**된다.
      표본이 쌓이기 전까지 임계값은 건드리지 않는다.
- [ ] **다른 모터로 프로파일 격리 확인**
      프로파일 구조는 모터별로 설계됐으나 실기는 이 유닛 1대뿐이다.

## 잠긴 채로 두는 것 (근거 생기기 전까지)

- STO/E-stop 효력 증거 → Finite PTP NEED-DATA 해제 선행조건
- 영구 저장(SV) 경로 — durable pre-assignment WAL authority 미구현
- 보호 기능(과전류·과온·위치오차 트립) 효력

---

## 다음 실기 세션 순서

```
연결 → Phase 1 → 서명 → Phase 2 → Session Zero → Apply → Verify → Jog
                                    ↑ Apply 앞이어야 함
```

전원을 껐다면 앞에 커뮤 ID가 필요하다(§3.2). 상세는 status §3.

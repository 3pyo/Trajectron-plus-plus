# G1 추론 구현 검증 — 2026-10-12

기존 `int_ee` checkpoint 12와 CPU Docker 이미지를 사용하여 실제 G1 데이터 두 개와
짧은 관측 구간의 추론을 실행했다. 아래 결과는 실행·입력 처리·시간 경계 검증이다.
별도의 위험도 검출이나 예측 정확도 평가를 수행한 것은 아니다.

## 실제 데이터 테스트 런

| 입력 / 설정 | 실제 모델 입력 | 예측 | 결과 |
|---|---|---|---|
| `safe_2`, 첫 metadata +6초 cutoff | 8개 시점 / 3.5초 | 20개 샘플 + 대표 궤적, 미래 3초 | 통과 |
| `danger_2`, 첫 metadata +6초 cutoff | 8개 시점 / 3.5초 | 20개 샘플 + 대표 궤적, 미래 3초 | 통과 |
| `danger_2_short`, 명시적 1.5초 관측 창 | 3개 시점 / 1.0초 | 10개 샘플 + 대표 궤적, 미래 3초 | 통과 |

모두 출력 shape와 유한값 검사를 통과하고 PNG/SVG를 생성했다.
격자는 관측 종료 시각에 맞춰 생성한다. 첫 격자는 관측 시작 이전의 측정 없이 보간할 수 없어
제외됐으며, 이력 padding은 기존 Trajectron++ 구현이 처리했다.

| 런 | 예측 기준 시각 ns | 요청 cutoff에서 뒤로 맞춘 시간 |
|---|---|---|
| `safe_2` | `1783504691514313472` | 0.129099264초 |
| `danger_2` | `1783504958278905856` | 0.001419776초 |
| `danger_2_short` | `1783504958278905856` | 0초 |

실제 실행 명령은 외부 `logs/commands.jsonl`의 `g1-safe-final-run`, `g1-danger-final-run`,
`g1-short-window-run`과 각 `g1-inference-container` 기록에 남아 있다.
짧은 관측 구간 런은 `/tmp`에서 절대 경로로 실행하여 작업 디렉터리에 의존하지 않는 것도 확인했다.

결과 파일은 소스 밖에 보관한다:

- Safe: [그림](../../../trajectron_runtime/results/g1-inference/20261012T085139.403681Z/prediction/pedestrian_000.png), [예측 JSON](../../../trajectron_runtime/results/g1-inference/20261012T085139.403681Z/prediction/predictions.json), [실행 보고서](../../../trajectron_runtime/results/g1-inference/20261012T085139.403681Z/prediction/inference-report.json)
- Danger: [그림](../../../trajectron_runtime/results/g1-inference/20261012T085139.402929Z/prediction/pedestrian_000.png), [예측 JSON](../../../trajectron_runtime/results/g1-inference/20261012T085139.402929Z/prediction/predictions.json), [실행 보고서](../../../trajectron_runtime/results/g1-inference/20261012T085139.402929Z/prediction/inference-report.json)
- 짧은 관측: [그림](../../../trajectron_runtime/results/g1-inference/20261012T085402.785402Z/prediction/pedestrian_000.png), [관측 상태](../../../trajectron_runtime/results/g1-inference/20261012T085402.785402Z/prediction/observation.json)

위 링크는 현재 워크스페이스의 보존된 결과를 가리킨다. 저장소 clone만으로는 외부 결과가 포함되지 않는다.

## 회귀 테스트

[최종 테스트 결과](../../../trajectron_runtime/results/g1-tests/20261012T085139.403084Z/tests.json):
**15개 테스트 통과, 실패·오류·skip 0개.**

실제 checkpoint를 사용하는 두 보행자 synthetic 장면과 G1 `safe_2`, `danger_2` 장면에서
cutoff 이후의 위치를 큰 값으로 변경해도 관측 상태, 그래프 adjacency/edge scaling,
동일 seed의 샘플·대표 예측이 정확히 동일했다.

나머지 검사는 위치에서 계산한 속도·가속도, coasting/갱신되지 않은 측정 제외,
중복 track stamp, 외삽 금지, 긴 결측의 Node 분리, 명시적 관측 시작 제한,
혼합 좌표계 거부, 세션·실험별 ID 분리, 최소 이력, 역방향 cutoff 정렬,
대상 선택 시 주변 보행자 보존, 미래 추적 stamp와 늦은 metadata 제외를 확인한다.

실제 데이터는 각각 보행자 한 명이므로, 상호작용 경로의 구동 검사는 두 보행자 synthetic
테스트로 수행했다. 실제 여러 보행자 데이터에서의 성능은 후속 검증 대상이다.

## 모델과 호스트 보존

- Python 3.6.15 / PyTorch 1.4.0+cpu / NumPy 1.16.4 / Pandas 0.25.1 / Matplotlib 3.1.3.
- checkpoint SHA256: `3fcc65cd8f48b70fce4965813e503e03c664e027f1f83f8a27d317773a138028`.
- 모델 설정 SHA256: `3538638ef65601e80dd2ac146d1a3f7ca87fa28fc2936bae2cb2adea2b18923d`.
- checkpoint 로딩 후 새 모듈이 추가되지 않는 것을 검사했다. 기존 모델·config·checkpoint는 수정하지 않았다.
- 기존 이미지와 의존성을 재사용했다. 호스트 pip/apt/colcon 설치·빌드나 ROS2 실행을 수행하지 않았다.
- [호스트 보존 검사](../../../trajectron_runtime/logs/g1-inference-preservation-report.json)에서
  기존 보호 파일 **885개**의 수정·삭제가 없고, 활성 호스트 Python과 배포판 **136개**의 버전이 동일했다.
  이 검사는 기록된 소스·설정·환경 정보의 비교이며 전체 호스트 파일시스템 감시는 아니다.
- 수정한 기존 파일은 런타임 README이며,
  `baselines/trajectron_runtime/backups/20261012T085324.556102Z/README.md`에 먼저 백업했다.
  신규 구현 파일의 후속 보완도 별도 backup manifest와 함께 보존했다.
- Git commit/staging/push는 수행하지 않았다.

## 그림에서 확인되는 한계

`danger_2`에서는 이후 측정 궤적이 방향을 바꾸는 반면, 예측은 관측 종료 시점의 이동을
이어가는 모습이 보인다. 실행 성공을 G1 환경의 정확도 검증으로 해석하면 안 된다.
녹색 디버깅 궤적은 측정으로 갱신된 추적기 위치이며 독립적인 ground truth가 아니다.
이후 데이터가 없거나 보간 근거가 부족한 시점은 그림에서 연결하지 않는다.

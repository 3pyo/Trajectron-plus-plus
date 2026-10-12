# G1 보행자 미래 궤적 예측

G1 파이프라인의 `metadata/frames.jsonl`을 저자의 **nuScenes int_ee checkpoint 12**에
입력하여 보행자의 미래 **3초 / 6개 시점**을 예측한다. 기존 모델·checkpoint·config는
수정하지 않으며, 재학습하지 않는다. Python/ROS2 의존성은 호스트에 설치하지 않는다.

## 처리 흐름과 파일 역할

```text
G1 case_logger의 frames.jsonl
  ↓ 관측 구간 제한 + 측정이 갱신된 보행자 추적만 선택
  ↓ 0.5초 간격 위치 재표본화 → 속도 → 가속도
Environment → Scene → PEDESTRIAN Node
  ↓ 관측 구간만으로 scene graph 생성
int_ee checkpoint 12 / CPU
  ↓ 미래 0.5, 1.0, …, 3.0초
예측 JSON + 관측 상태/보간 근거 JSON + PNG/SVG
```

| 파일 | 역할 |
|---|---|
| [adapter.py](adapter.py) | JSONL 읽기, 관측 제한, 측정 필터, 재표본화, 상태와 환경 객체 구성 |
| [infer.py](infer.py) | checkpoint 로딩, 샘플·대표 궤적 예측, 결과와 시각화 저장 |
| [test_adapter.py](test_adapter.py) | 시간 경계·결측·식별·좌표계·실제 checkpoint 회귀 테스트 |
| [run_inference.py](../../trajectron_runtime/run_inference.py) | 호스트 표준 라이브러리만 사용하는 Docker 추론 실행기 |
| [run_adapter_tests.py](../../trajectron_runtime/run_adapter_tests.py) | 동일 격리 조건의 Docker 테스트 실행기 |

입력은 `case_logger.v1`과 `case_logger.offline.v1` 스키마를 지원한다.
`g1_slam_report`의 로봇 CSV·지도만으로는 보행자 관측 이력을 만들 수 없다.

## 입력 규칙

1. 식별자는 `experiment_id + tracking_session_id + person_id`로 구성한다.
   결측으로 분리한 연속 구간에는 별도 segment 번호를 붙인다.
   `segmentation_instance_id`를 지속적인 보행자 ID로 사용하지 않는다.
2. `track.position.x/y`와 **`tracking.frame_id`**를 사용한다. 최상위 `frame_id`는
   카메라 좌표계이므로 사용하지 않는다. 혼합 좌표계는 오류로 종료한다.
   `relative_to_robot`나 이미지·지도·로봇 궤적은 모델 입력에 넣지 않는다.
3. `track_status=confirmed`, `missed_frames=0`,
   `last_measurement_stamp == track_stamp`인 기록만 사용한다.
   위치는 측정으로 갱신된 **추적기 상태 추정값**이며 원시 LiDAR 중심점이 아니다.
   `coasting`, 누락된 추적, 갱신되지 않은 측정, 비유한 위치는 제외한다.
4. 시간은 정수 nanosecond로 처리한다. 이미지/metadata 시간과 track 시간 모두
   관측 구간 안이어야 한다. 동일 track stamp는 중복 제거하고, 위치가 충돌하면 오류로 종료한다.
5. 예측 시각을 기준으로 0.5초 간격의 최대 9개 위치를 구성한다.
   정확한 측정점이 없으면 양쪽 측정 사이를 선형 보간한다.
   기본 최대 보간 간격은 0.5초이며, 외삽하지 않는다.
   긴 결측은 별도 Node로 분리하고, 현재까지 연결된 구간만 예측 대상으로 삼는다.
   관측 시작의 격자가 정확한 측정점이 아니면, 시작 이전 데이터를 끌어오지 않으므로
   첫 격자는 제외될 수 있다. 따라서 4초 창도 실제 입력은 8개 시점이 될 수 있다.
6. 재표본화한 위치에 기존 `derivative_of()`를 적용하여 속도와 가속도를 계산한다.
   상태 열 순서는 `[x, y, vx, vy, ax, ay]`이다.
   G1이 기록한 Kalman filter 속도는 모델 입력에 사용하지 않는다.
7. 예측 대상은 기본적으로 현재 시점을 포함한 연속 3개 이상의 격자점이 필요하다.
   주변 보행자 구간은 2개 이상이면 그래프에 보존한다.
   모델의 `VEHICLE`, `PEDESTRIAN` 타입, 저자의 정규화와 attention radius는 유지하되,
   실제 Node는 보행자만 생성한다. 존재하지 않는 차량·로봇을 만들어 넣지 않는다.

## 미래 정보 제한과 RAG 비교

**관측 구간을 먼저 자른 뒤** 보간·미분·Scene·그래프를 생성하고 마지막 시점에서
`predict(min_future_timesteps=0)`을 호출한다. 전체 궤적에서 먼저 미분하거나 그래프를
만드는 방식은 사용하지 않는다. 관측 범위 내부의 중앙 차분은 허용하지만 관측 종료 이후
데이터는 어떤 상태에도 반영하지 않는다.

명시적 cutoff가 실제 측정 시각과 일치하지 않으면, cutoff 이하의 가장 최근 유효 측정으로
예측 시각을 뒤로 맞춘다. 대상 보행자를 지정하면 해당 대상의 측정으로 맞춘다.
`requested_cutoff_ns`, `prediction_time_ns`, `cutoff_snap_back_sec`를 기록한다.
따라서 RAG의 `t2`와 비교할 때 실제 예측 시각이 같은지 확인해야 한다.
관측 시작을 지정하지 않으면 실제 예측 시각 이전 4초를 사용한다.
`--observation-start-ns`로 `t1`을 지정하면 그 이전 기록은 사용하지 않는다.
격자는 예측 시각에 맞추므로 `t1` 바로 다음 격자부터 시작할 수 있다.

`--debug-future`는 두 번의 예측 호출이 끝난 **뒤**에 이후 추적 위치를 읽어 그림에 표시한다.
이 정보는 Scene·그래프·모델에 전달하지 않는다. 독립적으로 측정한 실제 궤적 정답은 아니다.

## 실행

아래 명령은 `Trajectron-plus-plus` 저장소 루트에서 실행한다.
기존 이미지 `g1-trajectron-int-ee:cpu-py36-20261012`를 그대로 사용하므로 재빌드는 필요 없다.
이미지 준비 방법은 [런타임 README](../../trajectron_runtime/README.md)를 참고한다.

```bash
python3 -B trajectron_runtime/run_logged.py --label g1-safe-run -- \
  python3 -B trajectron_runtime/run_inference.py \
  --input /home/choi/g1_ros2_ws/src/test_result/safe_2/metadata/frames.jsonl \
  --experiment-id safe_2 \
  --end-offset-sec 6 --samples 20 --seed 0 --debug-future
```

`--end-offset-sec`는 첫 보행자 metadata 시각에서의 경과 시간이다.
생략하면 마지막 보행자 metadata 시각을 cutoff로 사용한다. 마지막 이후 정답이 없어도 예측한다.
실제 데이터에 맞춰 `--input`과 구분 가능한 `--experiment-id`를 지정한다.

RAG와 동일한 관측 경계를 지정하는 예:

```bash
python3 -B trajectron_runtime/run_logged.py --label g1-rag-window -- \
  python3 -B trajectron_runtime/run_inference.py \
  --input /path/to/metadata/frames.jsonl \
  --experiment-id experiment_01 \
  --observation-start-ns 1783504685643412736 \
  --prediction-time-ns 1783504691514313472 \
  --target-session pedestrian_lidar_fusion_node_0 --target-person-id 1
```

두 ns 값은 예시이므로 실제 case의 `t1`, `t2`로 바꾼다.
짧은 관측 이력도 처리하지만 기본 최소 3개 격자점보다 적으면 명시적으로 실패한다.
대상을 지정해도 같은 관측 구간의 다른 보행자는 그래프에 유지한다.

| 옵션 | 기본값 / 의미 |
|---|---|
| `--samples` | 20 / 확률적 미래 궤적 수, 1..2000 |
| `--seed` | 0 / 동일 입력의 재현성 |
| `--max-gap-sec` | 0.5 / 보간을 허용할 두 측정의 최대 간격 |
| `--min-history-points` | 3 / 현재를 포함한 최소 연속 격자점, 2..9 |
| `--debug-future` | 꺼짐 / 이후 측정 궤적을 별도로 시각화 |
| `--state-root` | 저장소 옆 `trajectron_runtime/` / 로그·결과 루트 |
| `--output-root` | 외부 state의 `results/g1-inference/` |

## 결과와 시각화

실행 시 `RESULT_DIRECTORY=...`가 출력된다. 기본 결과 위치는 다음과 같다.

```text
baselines/trajectron_runtime/results/g1-inference/<UTC timestamp>/
├─ launch-manifest.json        # 정확한 Docker argv·마운트
├─ exit-status.json
└─ prediction/
   ├─ observation.json        # 6차원 상태·시각·보간 근거·제외 수·식별자
   ├─ predictions.json        # 보행자별 샘플·대표 궤적과 미래 시각
   ├─ inference-report.json   # 버전·해시·예측 shape/유한값 검증
   ├─ debug-future.json       # --debug-future 사용 시에만 생성
   ├─ pedestrian_000.png
   └─ pedestrian_000.svg
```

`samples_xy`의 shape는 `[samples, 6, 2]`, `most_likely_xy`는 `[6, 2]`이다.
대표 궤적은 `z_mode=True, gmm_mode=True`로 구하며 샘플 평균이 아니다.
좌표는 입력과 동일한 tracking 좌표계의 미터 단위이다.

그림 왼쪽은 검은 관측 이력, 파란 예측 샘플(최대 50개 표시), 주황 대표 궤적,
빨간 현재 위치와 +0.5초 단위 주석을 보여준다.
`--debug-future`를 켜면 녹색 점선으로 이후 추적 위치를 함께 표시한다.
오른쪽은 입력 위치에서 계산한 vx/vy 이력으로, 미분 이상을 확인할 수 있다.

## Docker 격리와 로그

호스트 실행기는 표준 라이브러리만 사용하며 실제 NumPy/Pandas/PyTorch/Matplotlib 작업은
컨테이너 안에서 수행한다. 소스와 **입력 JSONL 한 파일**은 읽기 전용으로 연결하고,
새 외부 결과 폴더만 쓰기 가능하게 연결한다. 네트워크·GPU·호스트 Python·ROS2·홈·
Docker socket을 연결하지 않는다. 기존 `runc`, 비특권 UID/GID, 읽기 전용 rootfs,
2 CPU/2 GiB 제한을 유지한다.

컨테이너 커맨드는 외부 `logs/commands.jsonl`과 개별 `.log`에 자동 기록된다.
위의 `run_logged.py`까지 사용하면 호스트 실행기 호출도 기록된다.
결과는 새 timestamp 디렉터리에만 쓰고, 추론 스크립트는 비어 있지 않은 출력 폴더를 거부한다.
실패 시에도 실행 manifest·로그·종료 코드가 남는다.

## 테스트

```bash
python3 -B trajectron_runtime/run_logged.py --label g1-tests -- \
  python3 -B trajectron_runtime/run_adapter_tests.py \
  --fixtures-root /home/choi/g1_ros2_ws/src/test_result
```

테스트에서는 `safe_2`, `danger_2`의 JSONL 두 파일만 읽기 전용으로 연결한다.
결과는 외부 `results/g1-tests/<UTC timestamp>/tests.json`과 로그에 저장한다.
실제 checkpoint를 사용한 두 보행자 및 실제 G1 테스트에서, cutoff 이후 위치를 크게 바꿔도
입력 상태·그래프·샘플·대표 예측이 동일한지 확인한다.

이외에 위치 기반 미분, 갱신된 측정 필터, 외삽 방지, 긴 결측 분리, 명시적 관측 시작,
미래 시각으로 연결된 추적/늦게 기록된 metadata 제외, 좌표계·ID·중복·최소 이력 검사를 포함한다.

2026-10-12 구현 검증 결과와 결과 파일은 [검증 보고서](VALIDATION.md)에 정리했다.
예측 동작과 데이터 처리의 검증이며, 도메인 적합성·위험도 검출 성능을 입증하는 실험은 아니다.

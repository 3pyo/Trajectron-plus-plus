# Trajectron++ Docker 환경 구현 및 검증 결과

작업일: 2026-10-12 (Asia/Tokyo)

> 이 문서는 최초 컨테이너 구현 기록이다. 이후 구현 코드는 Trajectron++ 내부로
> 이동했고 생성 데이터는 기존 외부 경로에 보존했다. 현재 사용법은 README.md,
> 이동 검증은 RELOCATION_REPORT.md를 참고한다. 아래 기존 파일 보존 수치는
> 최초 작업 당시 결과이며, 이동 작업의 수치는 별도 보고서에 기록했다.

## 결과와 범위

`g1-trajectron-int-ee:cpu-py36-20261012` 이미지를 빌드하고 실제 컨테이너에서
CPU 추론 의존성 검증 32개를 통과했다. 저자의 `int_ee` checkpoint 12를 로딩하고
VEHICLE / PEDESTRIAN 모델을 초기화했다. 체크포인트 모듈 35개와 파라미터
268,562개를 확인했으며, 모델 생성 과정에서 추가 모듈이 임의 초기화되지 않았다.

이번 범위는 환경 설계·빌드·의존성 검증이다. G1 어댑터, 실험 데이터 변환,
미래 궤적 추론, 위험 판정, 학습, GPU 지원은 구현하거나 실행하지 않았다.

## 기존 환경 보존

이번 작업의 파일 쓰기는 `src/baselines/trajectron_runtime/`에 한정했다.
Docker 이미지·빌드 캐시는 기존 Docker daemon이 관리하는 저장소에 추가됐다.
호스트에서 pip/conda/apt 설치, ROS 빌드, 셸 설정 또는 드라이버 변경을 하지 않았다.
기존 Trajectron++ 저장소와 체크포인트도 수정하지 않았다.

작업 전후 비교 결과:

- 기록한 기존 소스·설정·체크포인트 및 선택한 셸/ROS setup 파일 876개: 변경·삭제 없음.
- 현재 호스트 Python 실행 경로·버전·prefix: 동일.
- 호스트 Python distribution 136개의 이름·버전 목록: 동일.

증거: [보존 검사 결과](../../trajectron_runtime/logs/host-preservation-report.json),
[작업 전 snapshot](../../trajectron_runtime/logs/host-before.json), [작업 후 snapshot](../../trajectron_runtime/logs/host-after.json).

원시 snapshot 전체 비교는 별도 `baselines/ablation/`에서 추가된 신규 파일 9개도
탐지하여 최초 비교 exit code가 1이었다. 이후 기존 파일의 변경·삭제와 신규 파일을
구분하여 보존 검사를 수행했다. 기존 876개 파일 및 Python 환경은 그대로였다.
ablation 신규 파일은 이번 작업이 만든 것이 아니며 수정하거나 제거하지 않았다.
이 검사는 기록한 항목의 비교이며 호스트 전체 파일시스템의 snapshot은 아니다.

## 컨테이너 구성

| 항목 | 구성 |
| --- | --- |
| 아키텍처 | linux/amd64 |
| Python | 3.6.15 |
| PyTorch | 1.4.0+cpu |
| NumPy / pandas / SciPy | 1.16.4 / 0.25.1 / 1.3.1 |
| orjson / ncls / dill | 2.1.4 / 0.0.51 / 0.3.1.1 |
| OpenCV | opencv-python-headless 4.1.1.26 |
| Matplotlib / seaborn | 3.1.3 / 0.9.0 |
| 빌드 도구 | pip 21.3.1, setuptools 59.6.0, wheel 0.37.1 |
| ncls 빌드용 Cython | 0.29.36; runtime에는 미설치 |

전체 Python 의존성은 [requirements.lock](requirements.lock)에 고정했다.
Python builder/runtime base image는 linux/amd64 digest로 고정했다.
오래된 ncls 원본 버전의 wheel을 빌더 내부에서 생성하고, runtime에 설치할 때는
BuildKit의 임시 wheel mount를 이용해 네트워크 없이 설치했다.

OpenCV import에서 `libgthread-2.0.so.0` 누락을 발견했다. Dockerfile 백업 후,
동일한 digest-pinned Debian builder의 GLib/GThread/PCRE 라이브러리를 runtime에
복사하여 해결했다. 이 과정에서도 apt 명령을 사용하지 않았다.
라이브러리 원본 패키지 버전은 GLib `2.58.3-2+deb10u3`, PCRE `2:8.39-12`이며,
복사한 바이너리의 SHA-256을 실제 runtime에서 검증했다.

TensorFlow·Jupyter·TensorBoard 및 원시 nuScenes 데이터 전처리용 선택 의존성은
CPU checkpoint 추론 검증 범위에 필요하지 않아 설치하지 않았다.
저자 requirements 전체를 설치한 학습/노트북 환경이라는 의미는 아니다.

## 파일 연결과 실행 제한

[검증 launcher](verify_container.py)는 매번 새 결과 디렉토리를 생성하고 다음
조건으로 실행한다.

- 원본 저장소 → `/opt/trajectron-src`: 읽기 전용.
- 새 검증 결과 디렉토리 → `/results`: 쓰기 가능.
- 호스트 Python/ROS 환경·home·Docker socket·실험 데이터·GPU: 연결하지 않음.
- root filesystem 읽기 전용, `/tmp`는 256 MiB의 임시 tmpfs.
- 네트워크 없음, 추가 capability 없음, no-new-privileges, runc runtime.
- UID/GID 1000:1000으로 검증; launcher는 실행자의 UID/GID 사용.
- CPU 2개, 메모리 2 GiB, swap 추가 사용 금지, PID 256개 제한.
- 실행 종료 시 해당 임시 컨테이너 자동 제거.

실제 인자는 [launch-manifest.json](../../trajectron_runtime/results/20261012T080111.999730Z/launch-manifest.json)에 기록했다.

## 실제 검증

[dependency-report.json](../../trajectron_runtime/results/20261012T080111.999730Z/dependency-report.json): **passed**.

- 고정한 Python package 버전과 Docker build의 `pip check`.
- torch/numpy/pandas/scipy/cv2 및 Trajectron++ environment/model/online/evaluation/
  visualization 모듈 import.
- CPU tensor 연산, ncls/orjson native extension, Environment dill round trip.
- checkpoint 12 로딩, 양쪽 node model 생성, 파라미터 finite 검사.
- 저자 nuScenes/pedestrian evaluate 및 online 실행 스크립트의 `--help` 진입점.
- 원본 source mount의 읽기 전용 여부와 공유 라이브러리 hash.

검증은 실제 데이터 예측 성능이나 GPU 실행을 보장하지 않는다.
체크포인트 SHA-256:

```text
3fcc65cd8f48b70fce4965813e503e03c664e027f1f83f8a27d317773a138028
```

## 로그와 백업

[commands.jsonl](../../trajectron_runtime/logs/commands.jsonl)에 각 명령 argv, shell 표현, 실행 시각,
작업 경로, 종료 코드, stdout/stderr log 파일을 기록했다. 실패한 빌드/검증 시도도
그대로 보존했다. 최초 read-only 점검은 [bootstrap-command.json](../../trajectron_runtime/logs/bootstrap-command.json)에
별도로 기록했으며, 점검 명령을 logger로 반복 실행하여 출력도 남겼다.
Docker build 내부 RUN 명령과 패키지 설치 출력은 빌드 log에 포함된다.

최초 Docker build 시 기존 buildx activity 디렉토리의 sandbox 쓰기 제한으로
실패했다. 빌드 권한을 요청하고 `BUILDX_CONFIG`를 새 runtime log 디렉토리로
지정하여 수행했다. 기존 Docker 사용자 설정은 수정하지 않았다.

이번에 새로 작성한 Dockerfile, verifier, README를 보완할 때도 수정 전에
`backups/`에 timestamped 사본과 hash를 남겼다. 기존 사용자 소스 수정은 없었다.
이미지·기존 컨테이너 삭제, Docker prune 등 파괴적인 작업은 수행하지 않았다.

## 재실행과 복구

작업 위치: `/home/choi/g1_ros2_ws/src`.

```bash
python3 -B baselines/Trajectron-plus-plus/trajectron_runtime/run_logged.py --label dependency-check -- \
  python3 -B baselines/Trajectron-plus-plus/trajectron_runtime/verify_container.py
```

현재 이미지 ID:

```text
sha256:4f3ac110c8106ff848b84ff832c0cfef1f8be50e040b28fe91fce3f11825d21d
```

Offline 복구용 image archive를 저장했다. 크기는 292,060,672 bytes (약 279 MiB).

```text
artifacts/g1-trajectron-int-ee-cpu-py36-20261012T080237.178963Z.tar
SHA-256: efcd1f4986026bfeece5d11487aa6a63f58fb5e30b37c5247fd868a9d473dc8c
```

[archive manifest](../../trajectron_runtime/artifacts/20261012T080237.178963Z_archive-manifest.json)에 이미지 ID,
archive hash, 저장 명령 및 복원 인자를 기록했다. tar manifest의 이미지 tag도
확인했다. 이 작업에서 실제 `docker image load` 복원 실행은 수행하지 않았다.

먼저 같은 artifacts 디렉토리의 `.tar.sha256` 파일로 archive 무결성을 확인한 뒤:

```bash
python3 -B baselines/Trajectron-plus-plus/trajectron_runtime/run_logged.py --label image-restore -- \
  docker image load --input \
  baselines/trajectron_runtime/artifacts/g1-trajectron-int-ee-cpu-py36-20261012T080237.178963Z.tar
```

원본 Trajectron++ 소스와 checkpoint는 archive에 포함하지 않고 별도 read-only
mount로 사용한다. 정확한 이미지 복구는 archive를 사용하며, 나중에 재빌드한
이미지가 byte 단위로 동일하다고 보장하지는 않는다.

환경 사용을 중단하면 호스트 Python/ROS 복구 작업은 필요 없다. 추후 삭제할 때는
이 작업의 특정 image/archive/results만 대상으로 하고 공용 Docker prune은 피한다.

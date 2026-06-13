# OPIC TTS

Chuyển các bài luyện nói OPIC có gắn thẻ người nói thành tệp MP3 bằng
Chatterbox TTS.

Hệ thống đọc lần lượt các đoạn `[SYSTEM]`, `[NPC]`, `[USER]`, tạo một tệp WAV
cho mỗi đoạn, chèn khoảng lặng giữa các đoạn rồi ghép chúng thành một tệp MP3.

## Cấu trúc dự án

```text
.
├── generate.py       # Chương trình chính
├── parser.py         # Phân tích nội dung và thẻ người nói
├── tts_engine.py     # Giao diện TTS và ChatterboxEngine
├── audio_utils.py    # Ghép WAV, chèn khoảng lặng và xuất MP3
├── config.yaml       # Cấu hình âm thanh, TTS và giọng đọc
├── input/            # Tệp văn bản đầu vào
├── output/           # Tệp MP3 đầu ra
├── voices/           # Tệp WAV giọng mẫu (không bắt buộc)
├── temp/             # Tệp WAV tạm thời
└── tests/            # Unit test
```

## Yêu cầu

- Python 3.10 trở lên
- FFmpeg
- Các thư viện trong `requirements.txt`

## Cài đặt

Tạo môi trường ảo và cài các thư viện:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

Kiểm tra FFmpeg:

```bash
ffmpeg -version
```

Nếu máy không có FFmpeg hệ thống, chương trình sẽ thử dùng bản được cung cấp
bởi `imageio-ffmpeg`.

## Định dạng đầu vào

Mỗi đoạn phải bắt đầu bằng một trong ba thẻ:

- `[SYSTEM]`
- `[NPC]`
- `[USER]`

Thẻ và nội dung có thể nằm cùng dòng:

```text
[SYSTEM] Let's begin the interview.
[NPC] Tell me about your neighborhood.
[USER] I live in a quiet neighborhood near a park.
```

Nội dung cũng có thể nằm trên nhiều dòng:

```text
[SYSTEM]
I would like to know where you live.
Can you describe your home?

[USER]
I live in a three-story house.
My favorite room is my bedroom.
```

Chương trình sẽ báo lỗi khi:

- Có thẻ người nói không được hỗ trợ.
- Một thẻ không có nội dung.
- Có nội dung trước thẻ đầu tiên.
- Tệp không chứa đoạn hội thoại hợp lệ.
- Tệp không phải UTF-8.

## Cấu hình

Các thiết lập nằm trong `config.yaml`:

```yaml
sample_rate: 24000
pause_ms: 700
output_format: mp3
mp3_bitrate: 192k
normalize_audio: true

tts:
  engine: chatterbox
  device: auto
  max_chunk_chars: 220
  sentence_pause_ms: 180
  model_options:
    exaggeration: 0.40
    cfg_weight: 0.30
    temperature: 0.80

voices:
  SYSTEM: null
  NPC: null
  USER: null
```

Ý nghĩa:

- `sample_rate`: tần số lấy mẫu của WAV được tạo.
- `pause_ms`: khoảng lặng giữa hai đoạn, tính bằng mili giây.
- `output_format`: hiện chỉ hỗ trợ `mp3`.
- `mp3_bitrate`: bitrate MP3; `192k` cho chất lượng tốt mà dung lượng vừa phải.
- `normalize_audio`: chuẩn hóa âm lượng trước khi xuất MP3.
- `tts.device`: thiết bị chạy mô hình, ví dụ `auto`, `cpu` hoặc `cuda`.
- `tts.max_chunk_chars`: giới hạn độ dài mỗi lần Chatterbox tạo âm thanh.
- `tts.sentence_pause_ms`: khoảng nghỉ ngắn giữa các câu trong cùng một đoạn.
- `tts.model_options`: tham số bổ sung truyền vào Chatterbox.
- `voices`: đường dẫn đến WAV giọng mẫu cho từng người nói.

Thiết lập gợi ý cho bài thi OPIC:

- `exaggeration: 0.40`: biểu cảm vừa phải, tránh giọng quá kịch.
- `cfg_weight: 0.30`: nhịp nói điềm tĩnh hơn mà không kéo giãn waveform.
- `temperature: 0.80`: mức mặc định ổn định của Chatterbox.

Để giọng giống người thật hơn, nên cung cấp một tệp WAV giọng mẫu sạch dài
khoảng 10-20 giây, chỉ có một người nói, không có nhạc hoặc tiếng ồn. Giọng mẫu
nên nói tiếng Anh với tốc độ và ngữ điệu gần với bài thi mong muốn.

`[SYSTEM]` và `[NPC]` hiện cùng dùng mẫu giọng nữ tiếng Anh LJSpeech tại
`voices/female_opic.wav`:

```yaml
voices:
  SYSTEM: voices/female_opic.wav
  NPC: voices/female_opic.wav
  USER: null
```

Mẫu này thuộc phạm vi công cộng. Thông tin nguồn và cách xử lý được ghi tại
`voices/README.md`.

Không nên làm chậm file WAV sau khi tạo vì time-stretch có thể làm giọng bị
rè, méo hoặc thiếu tự nhiên. Cấu hình trên giữ waveform gốc và tạo nhịp vừa
phải bằng cách chia câu, thêm khoảng nghỉ ngắn và điều chỉnh Chatterbox.

Ví dụ sử dụng giọng mẫu:

```yaml
voices:
  SYSTEM: voices/system.wav
  NPC: voices/npc.wav
  USER: voices/user.wav
```

Giá trị `null` sử dụng giọng mặc định của Chatterbox.

## Sử dụng

Tạo MP3 từ một tệp:

```bash
python3 generate.py input/Q23.txt
```

Tạo MP3 cho tất cả tệp `.txt` nằm trực tiếp trong một thư mục:

```bash
python3 generate.py input/
```

Sử dụng tệp cấu hình khác:

```bash
python3 generate.py input/Q23.txt --config path/to/config.yaml
```

Kết quả được lưu trong `output/` với tên giống tệp đầu vào:

```text
input/Q23.txt -> output/Q23.mp3
```

Các tệp WAV trung gian được tạo trong `temp/` và tự động xóa sau khi xử lý
xong từng tệp.

## Chạy kiểm thử

```bash
python3 -m unittest discover -s tests -v
```

## Thay đổi TTS engine

Mọi import và lời gọi API của Chatterbox được đặt trong `tts_engine.py`.
Nếu API của Chatterbox thay đổi, chỉ cần cập nhật `ChatterboxEngine` mà không
phải sửa parser hoặc quy trình ghép âm thanh.

# OPIC TTS

Chuyển các bài luyện nói OPIC có gắn thẻ người nói thành tệp MP3 bằng
Chatterbox TTS.

Hệ thống đọc lần lượt các đoạn `[SYSTEM]`, `[USER]`, tách nội dung
theo câu và marker pause, rồi xuất mỗi câu thành một tệp MP3 riêng trong folder
của bài.

## Cấu trúc dự án

```text
.
├── generate.py       # Chương trình chính
├── parser.py         # Phân tích nội dung và thẻ người nói
├── tts_engine.py     # Giao diện TTS và ChatterboxEngine
├── audio_utils.py    # Xử lý WAV và xuất MP3
├── config.yaml       # Cấu hình âm thanh, TTS và giọng đọc
├── input/            # Tệp văn bản đầu vào
├── output/           # Folder MP3 đầu ra theo category và bài
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

Mỗi đoạn phải bắt đầu bằng một trong hai thẻ:

- `[SYSTEM]`
- `[USER]`

Thẻ và nội dung có thể nằm cùng dòng:

```text
[SYSTEM] Let's begin the interview.
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

## Emotion, tốc độ và khoảng nghỉ

Có thể thêm emotion và tốc độ sau thẻ người nói:

```text
[SYSTEM][neutral][slow]
Please describe your home.

[USER][warm][medium]
I live in a quiet neighborhood. <pause:0.5>

[USER][happy][slow]
Overall, I really enjoy living there.
```

Cú pháp là `[SPEAKER][EMOTION][PACE]`:

- Emotion: `neutral`, `calm`, `warm`, `happy`, `excited`, `surprised`,
  `worried`, `concerned`, `disappointed`, `frustrated`, `relieved`,
  `grateful`, `curious`, `polite`, `professional`, `reassuring`,
  `embarrassed`, `determined`.
- Pace: `slow`, `medium`, `fast`.
- `<pause:0.5>` hoặc `[pause:0.5]` đánh dấu nhịp nghỉ để tách câu; marker này
  không được đọc thành lời và không tạo file âm thanh riêng.

`cooperative` vẫn được hỗ trợ để tương thích với các script cũ.

Emotion được chuyển thành tham số `exaggeration` của Chatterbox. Pace điều
chỉnh `cfg_weight` và khoảng nghỉ giữa câu. Chatterbox hiện tại không hỗ trợ
instruction dạng văn bản trực tiếp, vì vậy các tag được ánh xạ sang những tham
số mà model thực sự hiểu.

Với cấu hình hiện tại, mọi tag tốc độ vẫn được ép về `slow`. Riêng `[USER]`
được đặt khoảng 70% tốc độ so với `[SYSTEM]` và giảm thêm 7%. `[SYSTEM]` bỏ qua
các giảm tốc này để giữ nhịp đọc đề ngắn gọn hơn.

Các emotion dễ làm model nói nhanh được override sang style chậm hơn trong
`config.yaml`, ví dụ `excited`, `surprised`, `happy`, `grateful` dùng style
`warm`; `worried`, `frustrated` dùng `concerned`; `determined` dùng
`professional`.

Riêng `excited` được giữ mức biểu cảm vừa phải: vẫn có cảm xúc nhưng không dùng
exaggeration quá cao vì dễ làm model tự đọc nhanh.

Khi generate, mỗi câu hoặc mỗi phần text nằm giữa các marker `<pause:...>` /
`[pause:...]` sẽ được xuất thành một MP3 riêng.

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
mp3_bitrate: 256k
output_sample_rate: 44100
output_channels: 2
normalize_audio: false
regenerate_existing: false

tts:
  engine: chatterbox
  device: auto
  max_chunk_chars: 220
  sentence_pause_ms: 180
  pace_override: slow
  emotion_overrides:
    excited: warm
    surprised: warm
    happy: warm
    grateful: warm
    curious: polite
    worried: concerned
    frustrated: concerned
    determined: professional
  voice_lead_in_ms: 45
  voice_fade_in_ms: 35
  chunk_fade_out_ms: 20
  user_tail_silence_ms: 500
  model_options:
    exaggeration: 0.40
    cfg_weight: 0.30
    temperature: 0.80

voices:
  SYSTEM: null
  USER: null
```

Ý nghĩa:

- `sample_rate`: tần số lấy mẫu của WAV được tạo.
- `pause_ms`: cấu hình cũ cho chế độ ghép file; khi xuất từng câu, nhịp tách
  được điều khiển bằng câu và marker `<pause:...>` / `[pause:...]`.
- `output_format`: hiện chỉ hỗ trợ `mp3`.
- `mp3_bitrate`: bitrate MP3; mặc định `256k`.
- `output_sample_rate`: sample rate của MP3 đầu ra; mặc định `44100` Hz.
- `output_channels`: `2` để xuất stereo hoặc `1` để xuất mono. Vì Chatterbox
  tạo mono nên stereo đầu ra là dual-mono, không phải hiệu ứng không gian giả.
- `normalize_audio`: chuẩn hóa âm lượng trước khi xuất MP3.
- `regenerate_existing`: khi là `false`, bỏ qua các file đã có MP3 tương ứng.
- `tts.device`: thiết bị chạy mô hình, ví dụ `auto`, `cpu` hoặc `cuda`.
- `tts.max_chunk_chars`: giới hạn độ dài mỗi lần Chatterbox tạo âm thanh.
- `tts.sentence_pause_ms`: khoảng nghỉ ngắn giữa các câu trong cùng một đoạn.
- `tts.pace_override`: khi đặt là `slow`, mọi tag `[medium]` và `[fast]` trong
  script vẫn được parse hợp lệ nhưng lúc generate sẽ dùng cấu hình tốc độ
  `slow`. Đặt `null` hoặc xóa dòng này nếu muốn dùng đúng tốc độ trong file TXT.
- `tts.voice_lead_in_ms`: thêm một khoảng đệm ngắn trước mỗi câu dùng voice
  clone để giảm artefact ở đầu câu.
- `tts.voice_fade_in_ms`: fade-in đầu waveform của voice clone, không thay đổi
  tốc độ hoặc cao độ.
- `tts.chunk_fade_out_ms`: fade-out ngắn ở cuối mỗi phần trước pause để giảm
  âm thừa do model tạo ra.
- `tts.user_tail_silence_ms`: thêm khoảng lặng sạch vào cuối mỗi MP3 của
  `[USER]`. Cách này làm nhịp luyện chậm hơn mà không kéo giãn hoặc làm méo
  giọng nói.
- `tts.model_options`: tham số bổ sung truyền vào Chatterbox.
- `voices`: đường dẫn đến WAV giọng mẫu cho từng người nói.

Thiết lập gợi ý cho bài thi OPIC:

- `exaggeration: 0.40`: biểu cảm vừa phải, tránh giọng quá kịch.
- `cfg_weight: 0.30`: nhịp nói điềm tĩnh hơn mà không kéo giãn waveform.
- `temperature: 0.80`: mức mặc định ổn định của Chatterbox.

Để giọng giống người thật hơn, nên cung cấp một tệp WAV giọng mẫu sạch dài
khoảng 10-20 giây, chỉ có một người nói, không có nhạc hoặc tiếng ồn. Giọng mẫu
nên nói tiếng Anh với tốc độ và ngữ điệu gần với bài thi mong muốn.

`[SYSTEM]` dùng mẫu giọng nữ riêng:

```yaml
voices:
  SYSTEM: voices/female.wav
  USER: null
```

File WAV được chuyển đổi từ MP3 do người dùng cung cấp. Chi tiết được ghi tại
`voices/README.md`.

Không nên làm chậm file WAV sau khi tạo vì time-stretch có thể làm giọng bị
rè, méo hoặc thiếu tự nhiên. Cấu hình trên giữ waveform gốc và tạo nhịp vừa
phải bằng cách chia câu, thêm khoảng nghỉ ngắn và điều chỉnh Chatterbox.

Ví dụ sử dụng giọng mẫu:

```yaml
voices:
  SYSTEM: voices/system.wav
  USER: voices/user.wav
```

Giá trị `null` sử dụng giọng mặc định của Chatterbox.

## Sử dụng

Tạo MP3 từ một tệp:

```bash
python3 generate.py input/Q23.txt
```

Tạo MP3 cho tất cả tệp `.txt` trong một thư mục và các thư mục con:

```bash
python3 generate.py input/
```

Các file `.txt` nằm trực tiếp trong `input/` sẽ bị bỏ qua. Chỉ những file nằm
trong category, ví dụ `input/music/Q32.txt`, mới được tạo MP3.

Mặc định chương trình chỉ tạo các bài chưa có output. Nếu folder output của bài
đã có MP3 thì sẽ bị bỏ qua. Để ép tạo lại:

```bash
python3 generate.py input/ --rerun
```

Sử dụng tệp cấu hình khác:

```bash
python3 generate.py input/Q23.txt --config path/to/config.yaml
```

Kết quả giữ nguyên cấu trúc category của `input/`, nhưng mỗi bài là một folder
và mỗi câu là một MP3 riêng:

```text
input/park/Park 01.txt            -> output/park/Park 01/01.mp3
                                      output/park/Park 01/02.mp3
                                      output/park/Park 01/03.mp3

input/famous people/Famous people 01.txt
                                  -> output/famous people/Famous people 01/01.mp3
                                     output/famous people/Famous people 01/02.mp3
```

Các tệp WAV trung gian được tạo trong `temp/` và tự động xóa sau khi xử lý
xong từng tệp. Chương trình không còn ghép các câu thành một MP3 lớn.

## Chạy kiểm thử

```bash
python3 -m unittest discover -s tests -v
```

## Thay đổi TTS engine

Mọi import và lời gọi API của Chatterbox được đặt trong `tts_engine.py`.
Nếu API của Chatterbox thay đổi, chỉ cần cập nhật `ChatterboxEngine` mà không
phải sửa parser hoặc quy trình xuất âm thanh.

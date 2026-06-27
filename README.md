# DICOM PNG Exporter

Utilitario para ler arquivos DICOM, extrair metadados e exportar as imagens em PNG organizadas por paciente.

O script principal e [convert_dicom_to_png.py](convert_dicom_to_png.py). Ele procura arquivos DICOM no diretorio `input/`, agrupa por `PatientID` e grava os PNGs em `output/<patient_id>/`, seguindo a ordem de captura disponivel nos metadados.

## Estrutura

```text
.
├── convert_dicom_to_png.py
├── requirements.txt
├── input/
│   └── .gitkeep
└── output/
    └── .gitkeep
```

As pastas `input/` e `output/` ficam no repositorio, mas o conteudo delas e ignorado pelo Git. Isso evita subir exames DICOM, PNGs gerados e metadados de pacientes.

## Instalação

Ative o ambiente conda `myenv`:

```bash
conda activate myenv
```

Instale as dependencias:

```bash
python -m pip install -r requirements.txt
```

Alternativamente, sem ativar o ambiente:

```bash
conda run -n myenv python -m pip install -r requirements.txt
```

## Uso

Coloque os arquivos DICOM dentro de `input/`. Os arquivos podem estar sem extensao, desde que sejam DICOM validos.

Execute:

```bash
conda run -n myenv python convert_dicom_to_png.py --input input --output output
```

Para um teste rapido com poucos arquivos:

```bash
conda run -n myenv python convert_dicom_to_png.py --input input --output output_sample --max-files 3
```

## Opções

```text
--input      Diretorio de entrada com arquivos DICOM. Padrao: input
--output     Diretorio onde os PNGs serao gravados. Padrao: output
--max-files  Converte apenas os primeiros N arquivos DICOM com imagem.
```

## Saída

Para cada paciente, o script cria uma pasta usando o `PatientID`:

```text
output/
└── 41120920260525/
    ├── 0001_series-001_instance-0001_frame-001.png
    ├── 0002_series-001_instance-0001_frame-002.png
    └── metadata.csv
```

O nome dos PNGs segue este formato:

```text
<sequencia>_series-<series_number>_instance-<instance_number>_frame-<frame_number>.png
```

Arquivos DICOM multiframe geram um PNG por frame.

## Ordenação

A ordem de exportacao usa, nesta prioridade:

1. `AcquisitionDateTime`
2. `AcquisitionDate`
3. `AcquisitionTime`
4. `ContentDate`
5. `ContentTime`
6. `SeriesNumber`
7. `InstanceNumber`
8. `ImagePositionPatient`
9. nome do arquivo original

Isso tenta preservar a sequencia de captura mesmo quando parte dos metadados esta ausente.

## Metadados

Cada pasta de paciente recebe um `metadata.csv` com uma linha por PNG gerado.

Campos incluidos:

```text
output_file
source_file
patient_id
patient_name
study_date
study_time
series_number
instance_number
acquisition_datetime
acquisition_date
acquisition_time
content_date
content_time
image_position_patient
frame_number
```

## Tratamento de imagem

O script aplica alguns tratamentos comuns antes de salvar o PNG:

- `RescaleSlope` e `RescaleIntercept`
- `WindowCenter` e `WindowWidth`, quando disponiveis
- `VOI LUT`, quando disponivel pelo `pydicom`
- inversao de `MONOCHROME1`
- normalizacao para 8 bits
- suporte a imagens RGB e multiframe

Arquivos sem `PixelData`, como alguns Structured Reports (`SR`), sao ignorados e listados no resumo final.

## Privacidade

Os nomes das pastas e o `metadata.csv` podem conter identificadores de pacientes, como `PatientID` e `PatientName`. Nao suba o conteudo de `input/` ou `output/` para repositorios publicos ou ambientes compartilhados sem anonimizar os dados.

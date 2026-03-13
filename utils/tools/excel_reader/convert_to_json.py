import openpyxl
import json
from pathlib import Path

def convert_excel_to_json(excel_file: str, output_file: str):
    wb = openpyxl.load_workbook(excel_file, data_only=True)
    ws = wb.active  # Or specifically wb['dtListaDetalleFormulaciones']
    
    data = []
    headers = []
    
    # Iterate through rows
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if not any(cell is not None for cell in row):
            continue # Skip empty rows if any before headers

        if not headers:
            headers = [str(cell).strip() if cell is not None else f"Col_{j}" for j, cell in enumerate(row)]
        else:
            row_dict = {}
            for j, cell in enumerate(row):
                if j < len(headers):
                    row_dict[headers[j]] = str(cell).strip() if cell is not None else ""
            data.append(row_dict)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    print(f"¡Datos convertidos y guardados exitosamente en {output_file}!")

if __name__ == '__main__':
    excel_path = "01.  super paquete (1) v1.xlsx"
    json_path = "01.  super paquete (1) v1.json"
    convert_excel_to_json(excel_path, json_path)

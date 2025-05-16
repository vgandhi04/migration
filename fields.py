import requests
import csv
import os

AQ_ZOHO_ACCESS_TOKEN = os.getenv("AQ_ZOHO_ACCESS_TOKEN")
module_name = 'Accounts'  # Change to Contacts, Deals, etc.

url = f'https://www.zohoapis.com/crm/v7/settings/fields?module={module_name}'
headers = {
    'Authorization': f'Zoho-oauthtoken {AQ_ZOHO_ACCESS_TOKEN}'
}

try:
    response = requests.get(url, headers=headers)
    response.raise_for_status()  # Raises an HTTPError for bad responses
    fields = response.json().get('fields', [])
    print(f"Fields successfully retrieved for {module_name}")
    print(f"Total fields: {len(fields)}")

    with open(f'{module_name}_fields.csv', mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Field Label', 'API Name', 'Data Type', 'Values'])
        for field in fields:
            values = []
            data_type = field.get('data_type')
            if data_type == 'picklist' or data_type == 'multiselectpicklist':
                # Extract values from pick_list_values for picklist or multiselectpicklist
                values = [value.get('display_value') for value in field.get('pick_list_values', [])]
                print(f"{data_type} values for {field.get('field_label')}: {values}")  # Debug print
            elif data_type == 'boolean':
                # Boolean fields have true/false values
                values = ['true', 'false']
                print(f"Boolean values for {field.get('field_label')}: {values}")  # Debug print
            # Join values into a string for CSV
            values_str = '; '.join(values) if values else ''
            writer.writerow([
                field.get('field_label'),
                field.get('api_name'),
                data_type,
                values_str
            ])
    print(f"Fields successfully exported to {module_name}_fields.csv")

except requests.exceptions.HTTPError as http_err:
    print(f"HTTP error occurred: {http_err}")
    print(f"Response content: {response.text}")  # Print API error details
except requests.exceptions.RequestException as err:
    print(f"Error occurred: {err}")
except ValueError as json_err:
    print(f"JSON decoding error: {json_err}")
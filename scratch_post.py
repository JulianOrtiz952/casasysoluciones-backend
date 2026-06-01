import requests

url = "http://localhost:8000/api/v1/inmuebles/"
data = {
    'titulo': 'Test',
    'precio': '100',
    'direccion': 'Direccion',
    'descripcion': 'Desc',
    'estado': 'en_oferta',
    'portada_index': '0',
    'es_comercial': 'false',
    'en_conjunto': 'false',
    'administracion_incluida': 'false',
}
response = requests.post(url, data=data)
print(response.status_code)
print(response.text)

from rest_framework import serializers
from .models import Inmueble, Inquilino, HistorialAlquiler, ImagenInmueble

class ImagenInmuebleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImagenInmueble
        fields = ['id', 'imagen', 'es_portada', 'creado_en']

class InmuebleSerializer(serializers.ModelSerializer):
    imagenes = ImagenInmuebleSerializer(many=True, read_only=True)

    class Meta:
        model = Inmueble
        fields = '__all__'

class InquilinoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inquilino
        fields = '__all__'

class HistorialAlquilerSerializer(serializers.ModelSerializer):
    inmueble_detalle = InmuebleSerializer(source='inmueble', read_only=True)
    inquilino_detalle = InquilinoSerializer(source='inquilino', read_only=True)

    class Meta:
        model = HistorialAlquiler
        fields = '__all__'

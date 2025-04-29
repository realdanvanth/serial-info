from django.urls import path
from devices import views

urlpatterns = [
    path('serial/devices/', views.list_devices, name='list_devices'),
    path('serial/data/<str:port>/', views.get_serial_data, name='get_serial_data'),
    path('serial/data/view/<str:port>/', views.serial_data_view, name='serial_data_view'),
    path('serial/send/', views.send_serial, name='send_serial'),
]

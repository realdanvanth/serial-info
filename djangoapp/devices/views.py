import serial
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
import serial.tools.list_ports

ser_connections = {}
serial_buffers = {}

def list_serial_ports():
    available_ports = []
    ports = serial.tools.list_ports.comports()
    for port in ports:
        try:
            if port.device and port.device != 'n/a':
                # Try opening and immediately closing the port to check if it's usable
                with serial.Serial(port.device, 115200, timeout=1) as s:
                    pass
                available_ports.append(port.device)
        except (serial.SerialException, OSError):
            pass
    return available_ports

def get_serial_data(request, port):
    full_port = '/dev/' + port
    if full_port not in ser_connections:
        try:
            ser_connections[full_port] = serial.Serial(full_port, 115200, timeout=1)
        except serial.SerialException as e:
            return JsonResponse({'error': f'Failed to open port {port}: {str(e)}'}, status=400)

    ser = ser_connections[full_port]

    if full_port not in serial_buffers:
        serial_buffers[full_port] = []

    try:
        while ser.in_waiting > 0:
            line = ser.readline().decode('utf-8').strip()
            if line:
                return JsonResponse({'lines': [line]})
                # serial_buffers[full_port].append(line)
    except Exception as e:
        return JsonResponse({'error': f'Error reading from port {port}: {str(e)}'}, status=500)

    

def list_devices(request):
    try:
        available_ports = list_serial_ports()
        return render(request, 'devices_list.html', {'available_ports': available_ports})
    except Exception as e:
        return HttpResponse(f"Error listing devices: {str(e)}", status=500)

def serial_data_view(request, port):
    return render(request, 'serial_data.html', {'port': port})

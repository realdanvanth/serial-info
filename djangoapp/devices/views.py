import serial
import json
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
import serial.tools.list_ports
from .models import Port, SerialOutput # Assuming you still need models
from django.views.decorators.csrf import csrf_exempt
import time # Optional: for potential small delay after write
import atexit
# Shared connection pool (keep this global or manage appropriately)
ser_connections = {}
last_lines = {}  # cache to avoid saving duplicates

def list_serial_ports():
    available_ports = []
    ports = serial.tools.list_ports.comports()
    for port_info in ports:
        # Simple check, might need refinement based on your OS/device naming
        if 'ttyACM' in port_info.device or 'ttyUSB' in port_info.device or 'COM' in port_info.device:
             # Basic check if port is likely usable - opening it here can be slow/problematic
             # A better approach might be just listing likely candidates
             available_ports.append(port_info.device) # Store the full device path
    return available_ports

def get_serial_data(request, port):
    # Construct the full port name expected by pyserial (/dev/ttyACM0 etc.)
    # This assumes 'port' from the URL is like 'ttyACM0'. Adjust if needed.
    full_port = f'/dev/{port}'
    # If your URL already contains /dev/ttyACM0, just use: full_port = port

    if full_port not in ser_connections:
        try:
            print(f"Attempting to open {full_port} for reading...")
            ser_connections[full_port] = serial.Serial(full_port, 115200, timeout=0.1)
            print(f"Successfully opened {full_port}")
            time.sleep(0.5)
        except serial.SerialException as e:
            print(f"Failed to open port {full_port} for reading: {str(e)}")
            if full_port in ser_connections:
                del ser_connections[full_port]
            return JsonResponse({'lines': [], 'error': f'Failed to open port {full_port}: {str(e)}'})
        except Exception as e:
            print(f"Unexpected error opening port {full_port}: {str(e)}")
            if full_port in ser_connections:
                 del ser_connections[full_port]
            return JsonResponse({'lines': [], 'error': f'Unexpected error opening port {full_port}: {str(e)}'})

    ser = ser_connections.get(full_port)

    if not ser or not ser.is_open:
         print(f"Serial connection for {full_port} not found or closed.")
         if full_port in ser_connections:
             del ser_connections[full_port]
         return JsonResponse({'lines': [], 'error': f'Serial port {full_port} is not open.'})

    lines_read = []
    port_obj = None # To store the Port model instance

    try:
        new_data_saved = False # Flag to check if we need to prune

        while ser.in_waiting > 0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line: # Process only non-empty lines
                print(f"Read from {full_port}: {line}")
                lines_read.append(line) # Add to list for JSON response

                # --- Database Interaction ---
                try:
                    # 1. Get or Create Port object (only once per request if needed)
                    if port_obj is None:
                         port_obj, created = Port.objects.get_or_create(port=full_port)
                         if created:
                             print(f"Created Port DB entry for {full_port}")

                    # 2. Create SerialOutput entry
                    SerialOutput.objects.create(port=port_obj, output=line)
                    # print(f"Saved output to DB for {full_port}: {line[:30]}...") # Optional: log DB save
                    new_data_saved = True # Mark that we saved something

                except Exception as db_error:
                    # Log DB specific errors without crashing the read loop
                    print(f"Database Error saving output for {full_port}: {db_error}")
                # --- End Database Interaction for this line ---

        # --- Pruning Logic (Run only if new data was saved for this port) ---
        if new_data_saved and port_obj:
            try:
                # Get all entries for this port, ordered by time
                all_outputs = SerialOutput.objects.filter(port=port_obj).order_by('-timestamp')
                count = all_outputs.count()

                # If count exceeds 5, find IDs of older entries to delete
                if count > 5:
                    # Slicing the queryset to get items beyond the 5th one
                    ids_to_delete = list(all_outputs.values_list('id', flat=True)[5:])
                    if ids_to_delete:
                         deleted_count, _ = SerialOutput.objects.filter(pk__in=ids_to_delete).delete()
                         print(f"Pruned {deleted_count} old DB entries for {full_port}")

            except Exception as prune_error:
                 print(f"Error pruning old DB entries for {full_port}: {prune_error}")
        # --- End Pruning Logic ---

    except serial.SerialException as e:
         print(f"SerialException reading from {full_port}: {str(e)}. Closing port.")
         if ser: # Ensure ser exists before trying to close
             ser.close()
         # Remove from connections dict regardless of close success
         if full_port in ser_connections:
             del ser_connections[full_port]
         # Return previously read lines + error? Or just error? Let's return lines read so far.
         return JsonResponse({'lines': lines_read, 'error': f'Serial error on {full_port}: {str(e)}'})
    except Exception as e:
         print(f"Error reading from port {full_port}: {str(e)}")
         # Return lines read so far + error
         return JsonResponse({'lines': lines_read, 'error': f'Error reading from {full_port}: {str(e)}'})

    # Return all non-empty lines read in this interval
    return JsonResponse({'lines': lines_read}) # No error key if successful

# --- list_serial_ports, list_devices, serial_data_view, send_serial, close_all_serial_ports ---
# (Make sure they are still present in your views.py)


def list_devices(request):
    try:
        available_ports = list_serial_ports()
        # Ensure the ports passed to the template are the base names if needed by serial_data_view URL
        # e.g., extracting 'ttyACM0' from '/dev/ttyACM0'
        # This depends on how your urls.py is set up for serial_data_view
        context_ports = [p.replace('/dev/', '') for p in available_ports] # Adjust as needed
        return render(request, 'devices_list.html', {'available_ports': context_ports})
    except Exception as e:
        print(f"Error listing devices: {str(e)}") # Log error
        return HttpResponse(f"Error listing devices: {str(e)}", status=500)

def serial_data_view(request, port):
    # This view just renders the template. The actual data comes from get_serial_data via JS.
    # 'port' here should match the identifier used in the URL (e.g., 'ttyACM0')
    return render(request, 'serial_data.html', {'port': port})


@csrf_exempt
def send_serial(request):
    if request.method == 'POST':
        try:
            payload = json.loads(request.body.decode('utf-8'))
            data = payload.get('buffer')
            port = payload.get('port') # Expecting full path like /dev/ttyACM0 from JS

            if not port or data is None: # Check if data is None or empty string if needed
                return JsonResponse({'status': 'error', 'message': 'Missing port or buffer data'}, status=400)

            # --- Use the shared connection pool ---
            if port not in ser_connections:
                try:
                    print(f"Attempting to open {port} for sending...")
                    # Ensure correct baud rate and a small timeout
                    ser_connections[port] = serial.Serial(port, 115200, timeout=0.1)
                    print(f"Successfully opened {port} for sending.")
                    # Give the connection a moment to establish
                    time.sleep(0.5)
                except serial.SerialException as e:
                    print(f"Failed to open port {port} for sending: {str(e)}")
                    if port in ser_connections: # Clean up handle if creation failed partially
                         del ser_connections[port]
                    return JsonResponse({'status': 'error', 'message': f'Failed to open port {port}: {str(e)}'}, status=500)
                except Exception as e: # Catch other potential errors during open
                     print(f"Unexpected error opening port {port}: {str(e)}")
                     if port in ser_connections:
                         del ser_connections[port]
                     return JsonResponse({'status': 'error', 'message': f'Unexpected error opening port {port}: {str(e)}'}, status=500)

            ser = ser_connections.get(port) # Use .get for safety

            if not ser or not ser.is_open:
                # Connection died or was closed elsewhere. Try to reopen? Or report error.
                print(f"Connection for {port} lost before sending. Removing handle.")
                if port in ser_connections:
                    del ser_connections[port]
                # Optionally, try to reopen here, or just return error
                return JsonResponse({'status': 'error', 'message': f'Serial port {port} is not open. Please refresh or check connection.'}, status=500)

            # Write the data
            # Add newline if the receiving device expects it
            full_data = (data + '\n').encode('utf-8')
            print(f"Sending to {port}: {full_data}") # Log what's being sent
            ser.write(full_data)
            # Optional: ser.flush() # Ensure data is sent immediately

            # --- DO NOT read response here ---
            # --- DO NOT close the connection here ---

            return JsonResponse({'status': 'ok', 'message': f'Data sent to {port}'})

        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON payload'}, status=400)
        except serial.SerialException as e:
            # Handle write errors (e.g., port closed unexpectedly)
            print(f"SerialException during write to {port}: {str(e)}. Closing port.")
            if port in ser_connections:
                ser = ser_connections[port]
                try:
                    ser.close()
                except Exception: # Ignore errors during close
                     pass
                del ser_connections[port] # Remove potentially dead connection
            return JsonResponse({'status': 'error', 'message': f'Serial write error on {port}: {str(e)}'}, status=500)
        except Exception as e:
            # Catch other potential errors
            print(f"Unexpected error in send_serial for {port}: {str(e)}") # Log the error
            return JsonResponse({'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}, status=500)
    else: # Use else for clarity
        return JsonResponse({'error': 'Invalid request method'}, status=405)

# --- Add cleanup logic (optional but recommended) ---
# This is tricky in Django's stateless model. You might need:
# 1. A separate management command to close ports.
# 2. A timeout mechanism within get_serial_data/send_serial to close inactive ports.
# 3. Close ports on Django server shutdown (e.g., using atexit, but reliability varies).

# Example using atexit (place at the end of views.py)
import atexit
def close_all_serial_ports():
    print("Closing all open serial ports...")
    for port, ser in list(ser_connections.items()): # Use list to avoid modifying dict during iteration
        try:
            if ser and ser.is_open:
                print(f"Closing {port}")
                ser.close()
        except Exception as e:
            print(f"Error closing port {port}: {e}")
    ser_connections.clear()

atexit.register(close_all_serial_ports)

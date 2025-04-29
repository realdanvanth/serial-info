from django.db import models

class Port(models.Model):
    port = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.port

class SerialOutput(models.Model):
    port = models.ForeignKey(Port, on_delete=models.CASCADE, related_name='serial_outputs')
    output = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.port.port} @ {self.timestamp}: {self.output[:50]}"

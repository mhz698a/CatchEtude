import subprocess

# Ruta al script que quieres ejecutar
script_path = r"pendings_exec.pyw"

# Ruta al ejecutable de Python
python_path = r"C:\Program Files\Python312\python.exe"

# Nombre de las tareas
task_week = "Python_Task_Semana"
task_saturday = "Python_Task_Sabado"

# Comando base
cmd_week = f'schtasks /create /tn "{task_week}" /tr "{python_path} {script_path}" /sc weekly /d MON,TUE,WED,THU,FRI,SUN /st 20:15 /f'
cmd_sat = f'schtasks /create /tn "{task_saturday}" /tr "{python_path} {script_path}" /sc weekly /d SAT /st 14:15 /f'

try:
    subprocess.run(cmd_week, shell=True, check=True)
    print("Tarea de lunes a viernes y domingo creada correctamente.")

    subprocess.run(cmd_sat, shell=True, check=True)
    print("Tarea de sábado creada correctamente.")

except subprocess.CalledProcessError as e:
    print("Error al crear las tareas:", e)
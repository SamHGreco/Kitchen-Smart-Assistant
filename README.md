## Run on the Raspberry Pi
Place the following in a folder on the Desktop:
Folder Name: Grocery_Project
    `main.py` | Stand in main, starts UI, connects lookup and scanning NOTE will need to be reworked during integration/finalization
    `config.pi.json` | configuration set up
    `Barcode_Reader.py`| scanner 
    `product_Database.py` | product lookup
    `requirements.txt` | python dependancy for scanner
    `UI_Theme.py` | colors, fonts, window size
    `User_Interface.py` | display product, sensor readings, and buttons
    `.venv` | Gets created during the process
    `__pycache__` | Gets created during the process
    `.gitignore` | Gets created during the process
    `.pantry-touch.lock` | Gets created during the process
    `App_Worker.py` | Background tasks NOTE will need to be reworked during integration
    `Background_Jobs.py` | Background tasks NOTE will need to be reworked during integration
    `Calibration_Storage.py` | Stand-in calibration NOTE will need to be reworked during integration
    `Demo_Data.py` | Demo Data
    `Initialize_Data.py` | Initialize Data/UI
    `Input_Hooks.py` | Integration Hooks NOTE will need to be reworked during integration
    `Input_Validation.py` | input validator NOTE will need to be reworked during integration
    `Inventory_Database.py`| Stand-in inventory process NOTE will need to be reworked during integration
    `Inventory_Query.py` | Stand-in inventory querry NOTE will need to be reworked during integration
    `Pi_Hardware.py` | Stand-in hardware config NOTE will need to be reworked during integration
    `Prepare_Data.py` | prepare data 
    `requirements-pi.txt` | configuration file, easier to integrate/change things later
    `Scale_Calibration.py` | Stand-in calibration NOTE will need to be reworked during integration
    `Scale_Interface.py` | Stand-in scale NOTE will need to be reworked during integration
    `Sensor_Interfaces.py` | Stand-in interface connections NOTE will need to be reworked during integration
    `System_Clock.py` | System clock 
    `UI_Calibration.py` | UI calibration screen NOTE will need to be reworked during integration
    `UI_Environment.py`| UI environment screen NOTE will need to be reworked during integration
    `UI_Home.py` | UI home screen
    `UI_Inventory.py` | UI inventory screen
    `UI_Scale.py` | UI scale screen NOTE will need to be reworked during integration
    `UI_Scan.py` | UI scanning 
    `UI_Settings.py`| UI settings screen NOTE will need to be reworked during integration
    `UI_Widgets.py` | UI widgets
    `Wake_Events.py` | Wake event configuration NOTE will need to be reworked during integration

Place another Folder within this folder
Folder Name: data
    `barcode.db` | barcode database
    `catalog.sqlite.db` | catalog
    `Inventory.db` | stand in inventory

```bash
cd /Desktop/Grocery_Project
sudo apt update
sudo apt install python3-tk python3-venv python3-gpiozero python3-lgpio i2c-tools gpiod libgpiod-dev python3-dev build-essential
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
sudo usermod -aG gpio,i2c,dialout "$USER"
sudo raspi-config 
```
Enable I2C, disable serial login, enable serial hardware reboot
```bash
Sudo nano /boot/firmware/config.txt
```
At the bottom: Enable_uart=1, Dtoverlay=disable-bt
The next command should return a "doesn't exist" that's good
```bash
Sudo systemctl disable --now hciuart 
realpath /dev/serial0
```
realpath should return /dev/ttyAMA0
```bash
python Scanner_Setup.py probe --config config.pi.json
python Scanner_Setup.py configure --config config.pi.json --apply
python Scanner_Setup.py verify --config config.pi.json
```
should return with scanner settings verified
now test an item
```bash
python Scanner_Setup.py scan --config config.pi.json
```
Should return a set of numbers for the upc code

## Test the actual setup
```bash 
python main.py --serial --config config.pi.json --fullscreen
```
## DO NOT LOOK INTO THE SCANNER WHEN IT IS ON (I DID)

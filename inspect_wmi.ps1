# Check ACPI thermal zones (built-in Windows, no LHM needed)
$temps = Get-WmiObject -Namespace root/WMI -Class MSAcpi_ThermalZoneTemperature
foreach ($t in $temps) {
    $celsius = ($t.CurrentTemperature - 2732) / 10.0
    Write-Host ("Zone: {0}  Temp: {1:F1} C" -f $t.InstanceName, $celsius)
}

# Check AcerBiosConfigurationTool instance
Write-Host ""
Write-Host "=== AcerBiosConfigurationTool instances ==="
Get-WmiObject -Namespace root/WMI -Class AcerBiosConfigurationTool | Format-List

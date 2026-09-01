# BMO PC Agent — PowerShell helpers for things bmo_pc_agent.py can't do with
# plain stdlib (exact system volume, screenshots). Invoked as:
#   powershell -NoProfile -ExecutionPolicy Bypass -File pc_agent_helpers.ps1 -Action SetVolume -Value 40
#   powershell -NoProfile -ExecutionPolicy Bypass -File pc_agent_helpers.ps1 -Action Screenshot -Value "C:\path\shot.png"
#
# -Value is always passed as a genuine separate process argument by the
# Python side (never string-interpolated into a shell command), so this is
# safe even though Value ultimately traces back to a voice command.

param(
    [Parameter(Mandatory = $true)][string]$Action,
    [string]$Value
)

function Set-SystemVolume([double]$Percent) {
    Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
    int NotImpl1();
    int NotImpl2();
    int GetChannelCount(out uint channelCount);
    int SetMasterVolumeLevel(float level, System.Guid eventContext);
    int SetMasterVolumeLevelScalar(float level, System.Guid eventContext);
    int GetMasterVolumeLevel(out float level);
    int GetMasterVolumeLevelScalar(out float level);
    int SetChannelVolumeLevel(uint channelNumber, float level, System.Guid eventContext);
    int SetChannelVolumeLevelScalar(uint channelNumber, float level, System.Guid eventContext);
    int GetChannelVolumeLevel(uint channelNumber, out float level);
    int GetChannelVolumeLevelScalar(uint channelNumber, out float level);
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, System.Guid eventContext);
    int GetMute(out bool mute);
    int GetVolumeStepInfo(out uint step, out uint stepCount);
    int VolumeStepUp(System.Guid eventContext);
    int VolumeStepDown(System.Guid eventContext);
    int QueryHardwareSupport(out uint hardwareSupportMask);
    int GetVolumeRange(out float volumeMin, out float volumeMax, out float volumeStep);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    int Activate(ref System.Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev);
}

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int NotImpl1();
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }

public class AudioHelper {
    static IAudioEndpointVolume Vol() {
        var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
        IMMDevice dev = null;
        Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(0, 1, out dev));
        IAudioEndpointVolume epv = null;
        var epvid = typeof(IAudioEndpointVolume).GUID;
        Marshal.ThrowExceptionForHR(dev.Activate(ref epvid, 23, 0, out epv));
        return epv;
    }
    public static float Volume {
        get { float v = -1; Marshal.ThrowExceptionForHR(Vol().GetMasterVolumeLevelScalar(out v)); return v; }
        set { Marshal.ThrowExceptionForHR(Vol().SetMasterVolumeLevelScalar(value, System.Guid.Empty)); }
    }
}
'@ -ErrorAction Stop

    $level = $Percent / 100.0
    if ($level -lt 0) { $level = 0 }
    if ($level -gt 1) { $level = 1 }
    [AudioHelper]::Volume = $level
    Write-Output "Volume set to $Percent percent."
}

function Save-Screenshot([string]$Path) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
    Write-Output "Screenshot saved to $Path"
}

switch ($Action) {
    "SetVolume"  { Set-SystemVolume ([double]$Value) }
    "Screenshot" { Save-Screenshot $Value }
    default      { Write-Error "Unknown action: $Action"; exit 1 }
}

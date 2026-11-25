// SPDX-License-Identifier: GPL-3.0-only
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.ServiceProcess;
using Microsoft.Win32;
using Microsoft.Win32.SafeHandles;

internal static class MaintenanceSetup
{
    private const string Service = "CadenceStudio2Maintenance";
    private const string RemovalKey = @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\CadenceStudio2Maintenance";
    private static readonly string Programs = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
    private static readonly string App = Path.Combine(Programs, "Cadence 2.0");
    private static readonly string Tools = Path.Combine(Programs, "Cadence Studio Maintenance");
    private static readonly string Broker = Path.Combine(Tools, "CadenceMaintenance.exe");
    private static readonly string Data = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "CadenceStudio2");
    private static readonly string Store = Path.Combine(Data, "Maintenance");
    private static readonly SecurityIdentifier Admin = new SecurityIdentifier("S-1-5-32-544");
    private static readonly SecurityIdentifier SystemSid = new SecurityIdentifier("S-1-5-18");
    private static readonly SecurityIdentifier Users = new SecurityIdentifier("S-1-5-32-545");
    private static readonly SecurityIdentifier OwnerRights = new SecurityIdentifier("S-1-3-4");
    private static readonly SecurityIdentifier TrustedInstaller =
        new SecurityIdentifier("S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464");
    private const InheritanceFlags Children = InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit;

    [StructLayout(LayoutKind.Sequential)]
    private struct FileInformation
    {
        public uint Attributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr security,
        uint mode, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out FileInformation info);

    private static SecurityIdentifier ServiceSid()
    {
        return (SecurityIdentifier)new NTAccount(@"NT SERVICE", Service).Translate(typeof(SecurityIdentifier));
    }

    private static void Plain(string path)
    {
        for (string item = path; item != null; item = Path.GetDirectoryName(item))
        {
            FileAttributes attributes;
            try { attributes = File.GetAttributes(item); }
            catch (FileNotFoundException) { continue; }
            catch (DirectoryNotFoundException) { continue; }
            if ((attributes & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Unexpected reparse point: " + item);
        }
    }

    private static bool Privileged(IdentityReference identity)
    {
        return identity.Equals(Admin) || identity.Equals(SystemSid) || identity.Equals(TrustedInstaller);
    }

    private static void Protected(string path, SecurityIdentifier permittedService)
    {
        Plain(path);
        bool directory = Directory.Exists(path);
        if (!directory)
        {
            using (var handle = CreateFileW(path, 128, 7, IntPtr.Zero, 3, 0, IntPtr.Zero))
            {
                FileInformation info;
                if (handle.IsInvalid || !GetFileInformationByHandle(handle, out info) || info.Links != 1)
                    throw new IOException("Cannot validate the installed file: " + path);
            }
        }
        FileSystemSecurity acl = directory
            ? (FileSystemSecurity)Directory.GetAccessControl(path) : File.GetAccessControl(path);
        var owner = acl.GetOwner(typeof(SecurityIdentifier));
        if (!Privileged(owner))
            throw new UnauthorizedAccessException("The path must be owned by an administrator: " + path);
        const FileSystemRights changes = FileSystemRights.Write | FileSystemRights.Delete |
            FileSystemRights.DeleteSubdirectoriesAndFiles | FileSystemRights.ChangePermissions | FileSystemRights.TakeOwnership;
        foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
        {
            if (rule.AccessControlType != AccessControlType.Allow || (rule.FileSystemRights & changes) == 0)
                continue;
            if (Privileged(rule.IdentityReference) || rule.IdentityReference.Equals(permittedService))
                continue;
            if (rule.IdentityReference.Value == "S-1-3-0" && (rule.PropagationFlags & PropagationFlags.InheritOnly) != 0)
                continue;
            throw new UnauthorizedAccessException("A non-administrative principal can change " + path);
        }
    }

    private static void Allow(FileSystemSecurity acl, SecurityIdentifier id, FileSystemRights rights, InheritanceFlags flags)
    {
        acl.AddAccessRule(new FileSystemAccessRule(id, rights, flags, PropagationFlags.None, AccessControlType.Allow));
    }

    private static DirectorySecurity PrivateAcl(SecurityIdentifier sid, bool readable)
    {
        var acl = new DirectorySecurity();
        acl.SetOwner(Admin);
        acl.SetAccessRuleProtection(true, false);
        Allow(acl, Admin, FileSystemRights.FullControl, Children);
        Allow(acl, SystemSid, FileSystemRights.FullControl, Children);
        Allow(acl, OwnerRights, FileSystemRights.ReadPermissions, Children);
        if (readable) Allow(acl, Users, FileSystemRights.ReadAndExecute, Children);
        if (sid != null) Allow(acl, sid, FileSystemRights.Modify, Children);
        return acl;
    }

    private static bool ExistingService()
    {
        using (var key = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\" + Service))
        {
            if (key == null) return false;
            string image = Convert.ToString(key.GetValue("ImagePath"));
            string account = Convert.ToString(key.GetValue("ObjectName"));
            if (!String.Equals(image, "\"" + Broker + "\"", StringComparison.OrdinalIgnoreCase) ||
                !String.Equals(account, @"NT AUTHORITY\LocalService", StringComparison.OrdinalIgnoreCase) ||
                Convert.ToInt32(key.GetValue("Type")) != 16)
                throw new InvalidOperationException("The service name is in use by a different installation.");
            return true;
        }
    }

    private static void Sc(string options)
    {
        var info = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "sc.exe"), options);
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        using (var process = Process.Start(info))
        {
            if (!process.WaitForExit(30000) || process.ExitCode != 0)
                throw new InvalidOperationException("Windows did not complete the service configuration.");
        }
    }

    private static void Stop(bool cleanup)
    {
        if (!ExistingService()) return;
        using (var service = new ServiceController(Service))
        {
            if (service.Status == ServiceControllerStatus.Stopped)
            {
                if (!cleanup) return;
                service.Start();
                service.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(35));
            }
            if (cleanup)
            {
                service.ExecuteCommand(192);
                service.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromMinutes(4));
                return;
            }
            if (service.Status != ServiceControllerStatus.StopPending) service.Stop();
            service.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(60));
        }
    }

    private static void Prepare()
    {
        bool exists = ExistingService();
        SecurityIdentifier sid = exists ? ServiceSid() : null;
        Plain(Programs);
        foreach (string path in new[] { App, Tools, Data, Store })
        {
            Plain(path);
            if (Directory.Exists(path)) Protected(path, path == App || path == Store ? sid : null);
        }
        if (Directory.Exists(Tools))
            foreach (string file in Directory.GetFileSystemEntries(Tools))
                Protected(file, null);
        Stop(false);
    }

    private static void GrantProduct(SecurityIdentifier sid)
    {
        var rootAcl = Directory.GetAccessControl(App);
        Allow(rootAcl, sid, FileSystemRights.ReadAndExecute | FileSystemRights.CreateFiles |
            FileSystemRights.CreateDirectories, InheritanceFlags.None);
        Directory.SetAccessControl(App, rootAcl);
        string exe = Path.Combine(App, "Cadence.exe");
        Plain(exe);
        var fileAcl = File.GetAccessControl(exe);
        if (!HasModify(fileAcl, sid))
        {
            Protected(exe, null);
            Allow(fileAcl, sid, FileSystemRights.Modify, InheritanceFlags.None);
            File.SetAccessControl(exe, fileAcl);
        }
        var info = FileVersionInfo.GetVersionInfo(exe);
        if (info.FileMajorPart != 2)
            throw new InvalidDataException("The installation is not Cadence Studio 2.");
        string version = new Version(2, info.FileMinorPart, info.FileBuildPart).ToString();
        foreach (string relative in new[] { "Licences", "_internal", "_internal-" + version })
        {
            string folder = Path.Combine(App, relative);
            Plain(folder);
            if (!Directory.Exists(folder)) continue;
            var folderAcl = Directory.GetAccessControl(folder);
            if (!HasModify(folderAcl, sid))
            {
                Protected(folder, null);
                CheckTree(folder);
                Allow(folderAcl, sid, FileSystemRights.Modify, Children);
                Directory.SetAccessControl(folder, folderAcl);
            }
        }
    }

    private static bool HasModify(FileSystemSecurity acl, SecurityIdentifier sid)
    {
        foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier)))
            if (rule.IdentityReference.Equals(sid) && rule.AccessControlType == AccessControlType.Allow &&
                (rule.FileSystemRights & FileSystemRights.Modify) == FileSystemRights.Modify)
                return true;
        return false;
    }

    private static void CheckTree(string folder)
    {
        foreach (string path in Directory.EnumerateFileSystemEntries(folder))
        {
            Protected(path, null);
            if (Directory.Exists(path)) CheckTree(path);
        }
    }

    private static void ClearServiceStore(string directory)
    {
        Plain(directory);
        foreach (string child in Directory.EnumerateFileSystemEntries(directory))
        {
            var attributes = File.GetAttributes(child);
            if ((attributes & FileAttributes.Directory) == 0) File.Delete(child);
            else if ((attributes & FileAttributes.ReparsePoint) != 0) Directory.Delete(child, false);
            else ClearServiceStore(child);
        }
        Directory.Delete(directory, false);
    }

    private static void Remove()
    {
        if (!ExistingService()) return;
        var sid = ServiceSid();
        Protected(App, sid);
        Protected(Data, null);
        Protected(Store, sid);
        Stop(true);
        Sc("delete " + Service);
        ClearServiceStore(Store);
        Registry.LocalMachine.DeleteSubKeyTree(RemovalKey, false);
        if (Directory.GetFileSystemEntries(Data).Length == 0) Directory.Delete(Data, false);
        var acl = Directory.GetAccessControl(App);
        acl.PurgeAccessRules(sid);
        Directory.SetAccessControl(App, acl);
    }

    private static void Disable()
    {
        if (ExistingService())
        {
            var sid = ServiceSid();
            Protected(Tools, null);
            Protected(Data, null);
            Protected(Store, sid);
            Stop(false);
            var stateFile = Path.Combine(Store, "state.json");
            Plain(stateFile);
            if (File.Exists(stateFile))
            {
                var json = new System.Web.Script.Serialization.JavaScriptSerializer();
                var state = json.Deserialize<System.Collections.Generic.Dictionary<string,object>>(File.ReadAllText(stateFile));
                string phase = Convert.ToString(state["Phase"]);
                if (phase != "idle" && phase != "installed" && phase != "failed" && phase != "ready")
                {
                    using (var service = new ServiceController(Service)) service.Start();
                    throw new InvalidOperationException("Finish the current Cadence update first.");
                }
            }
            Sc("delete " + Service);
            ClearServiceStore(Store);
            if (Directory.GetFileSystemEntries(Data).Length == 0) Directory.Delete(Data, false);
        }
        Registry.LocalMachine.DeleteSubKeyTree(RemovalKey, false);
        foreach (string filename in new[] { "CadenceMaintenance.exe", "CadenceRestart.exe" })
        {
            string file = Path.Combine(Tools, filename);
            Plain(file);
            if (File.Exists(file)) File.Delete(file);
        }
        string removal = Path.Combine(Tools, "CadenceMaintenanceRemove.exe");
        if (File.Exists(removal))
        {
            Plain(removal);
            if (!MoveFileExW(removal, null, 4)) throw new IOException("Could not schedule removal at restart.");
        }
        MoveFileExW(Tools, null, 4);
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool MoveFileExW(string original, string replacement, uint flags);

    private static void Install()
    {
        Prepare();
        Protected(Tools, null);
        Protected(Broker, null);
        Protected(Path.Combine(Tools, "CadenceRestart.exe"), null);
        bool created = !ExistingService();
        if (created)
            Sc("create " + Service + " binPath= \"\\\"" + Broker + "\\\"\" start= auto type= own obj= \"NT AUTHORITY\\LocalService\"");
        try
        {
            // Interactive clients query the PID through SCM. They never send privileged service controls.
            Sc("sdset " + Service + " D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;CCLCRC;;;AU)");
            Sc("sidtype " + Service + " restricted");
            Sc("privs " + Service + " SeChangeNotifyPrivilege");
            var sid = ServiceSid();
            if (!Directory.Exists(Data)) Directory.CreateDirectory(Data, PrivateAcl(null, true));
            Protected(Data, null);
            if (!Directory.Exists(Store)) Directory.CreateDirectory(Store, PrivateAcl(sid, false));
            Protected(Store, sid);
            Directory.SetAccessControl(Store, PrivateAcl(sid, false));
            GrantProduct(sid);
            using (var service = new ServiceController(Service))
            {
                service.Start();
                service.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(35));
            }
        }
        catch
        {
            if (created && ExistingService()) { Stop(false); Sc("delete " + Service); }
            throw;
        }
    }

    private static void InstallResource(string name)
    {
        string target = Path.Combine(Tools, name);
        Plain(target);
        string temp = Path.Combine(Tools, ".cadence-" + Guid.NewGuid().ToString("N") + ".tmp");
        try
        {
            using (var source = Assembly.GetExecutingAssembly().GetManifestResourceStream("Cadence.Setup." + name))
            using (var output = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                if (source == null) throw new InvalidDataException("The configuration package is incomplete.");
                source.CopyTo(output);
                output.Flush(true);
            }
            if (File.Exists(target)) File.Replace(temp, target, null);
            else File.Move(temp, target);
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }

    private static void Enroll()
    {
        if (ExistingService())
        {
            Protected(Tools, null);
            Protected(Broker, null);
            using (var existing = new ServiceController(Service))
            {
                if (existing.Status == ServiceControllerStatus.Stopped) existing.Start();
                existing.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(35));
            }
            return;
        }
        Prepare();
        string exe = Path.Combine(App, "Cadence.exe");
        Protected(exe, null);
        if (FileVersionInfo.GetVersionInfo(exe).FileMajorPart != 2)
            throw new InvalidDataException("Cadence Studio 2 must already be installed in Program Files.");
        if (!Directory.Exists(Tools)) Directory.CreateDirectory(Tools, PrivateAcl(null, true));
        Protected(Tools, null);
        InstallResource("CadenceMaintenance.exe");
        InstallResource("CadenceRestart.exe");
        InstallResource("CadenceMaintenanceRemove.exe");
        Install();
        using (var entry = Registry.LocalMachine.CreateSubKey(RemovalKey))
        {
            entry.SetValue("DisplayName", "Cadence Studio 2 Maintenance");
            entry.SetValue("Publisher", "Cadence");
            entry.SetValue("UninstallString", "\"" + Path.Combine(Tools, "CadenceMaintenanceRemove.exe") + "\" disable");
            entry.SetValue("NoModify", 1, RegistryValueKind.DWord);
            entry.SetValue("NoRepair", 1, RegistryValueKind.DWord);
        }
    }

    private static int Main(string[] args)
    {
        if (!Environment.Is64BitProcess || args.Length > 1 ||
            !new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator))
            return 5;
        bool french = System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "fr";
        try
        {
            if (args.Length == 0)
            {
                Enroll();
                System.Windows.Forms.MessageBox.Show(french ? "Les mises à jour de Cadence sont activées." :
                    "Cadence updates are enabled.", "Cadence");
                return 0;
            }
            switch (args[0])
            {
                case "prepare": Prepare(); break;
                case "install":
                    Install();
                    Registry.LocalMachine.DeleteSubKeyTree(RemovalKey, false);
                    string previousRemover = Path.Combine(Tools, "CadenceMaintenanceRemove.exe");
                    Plain(previousRemover);
                    if (File.Exists(previousRemover)) File.Delete(previousRemover);
                    break;
                case "remove": Remove(); break;
                case "disable":
                    if (!String.Equals(Assembly.GetExecutingAssembly().Location,
                            Path.Combine(Tools, "CadenceMaintenanceRemove.exe"), StringComparison.OrdinalIgnoreCase))
                        return 87;
                    Disable(); break;
                default: return 87;
            }
            return 0;
        }
        catch (Exception error)
        {
            if (args.Length == 0)
                System.Windows.Forms.MessageBox.Show((french ? "Activation impossible. " : "Could not enable updates. ") +
                    error.Message, "Cadence", System.Windows.Forms.MessageBoxButtons.OK,
                    System.Windows.Forms.MessageBoxIcon.Error);
            else Console.Error.WriteLine(error.Message);
            return 1;
        }
    }
}

// SPDX-License-Identifier: GPL-3.0-only
using System;
using System.CodeDom.Compiler;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using Microsoft.CSharp;
using Microsoft.Win32.SafeHandles;
using Cadence.Maintenance;

internal static class MachineStoreTests
{
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern SafeFileHandle CreateFile(string path,uint access,uint share,IntPtr security,uint mode,uint flags,IntPtr template);
    static bool RestrictProduct(string path) {
        var identity=WindowsIdentity.GetCurrent();
        if(new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator))return false;
        var acl=new DirectorySecurity();acl.SetAccessRuleProtection(true,false);
        InheritanceFlags children=InheritanceFlags.ContainerInherit|InheritanceFlags.ObjectInherit;
        foreach(var admin in new[]{"S-1-5-18","S-1-5-32-544"})
            acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(admin),FileSystemRights.FullControl,children,PropagationFlags.None,AccessControlType.Allow));
        acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier("S-1-3-4"),FileSystemRights.ReadPermissions,children,PropagationFlags.None,AccessControlType.Allow));
        acl.AddAccessRule(new FileSystemAccessRule(identity.User,FileSystemRights.ReadAndExecute|FileSystemRights.CreateFiles|FileSystemRights.CreateDirectories,
            InheritanceFlags.None,PropagationFlags.None,AccessControlType.Allow));
        acl.AddAccessRule(new FileSystemAccessRule(identity.User,FileSystemRights.Modify,children,PropagationFlags.InheritOnly,AccessControlType.Allow));
        Directory.SetAccessControl(path,acl);
        if(!Directory.GetAccessControl(path).AreAccessRulesProtected) {
            Console.WriteLine("Filesystem did not apply the isolated product ACL");return false;
        }
        return true;
    }
    static void CheckRestricted(string path,uint access,string label) {
        using(var h=CreateFile(path,access,7,IntPtr.Zero,3,0x02000000,IntPtr.Zero)) {
            int error=Marshal.GetLastWin32Error();
            Check(h.IsInvalid && error==5,label+" (handle invalid="+h.IsInvalid+", error="+error+")");
        }
    }
    static string Hex(Stream input) {
        using(var hash=SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(input)).Replace("-","").ToLowerInvariant();
    }
    static string Digest(string file) { using(var input=File.OpenRead(file))return Hex(input); }
    static void Check(bool success,string label) { if(!success)throw new Exception(label);Console.WriteLine(label); }
    static void Invalid(Action action,string label) {
        try { action(); } catch(InvalidDataException) { Console.WriteLine(label);return; }
        throw new Exception(label);
    }
    static void Executable(string output,string version) {
        using(var provider=new CSharpCodeProvider()) {
            var parameters=new CompilerParameters {GenerateExecutable=true,OutputAssembly=output,CompilerOptions="/target:winexe"};
            var result=provider.CompileAssemblyFromSource(parameters,"[assembly:System.Reflection.AssemblyFileVersion(\""+version+".0\")] internal class Dummy { static void Main() {} }");
            if(result.Errors.HasErrors)throw new Exception(result.Errors[0].ErrorText);
        }
    }
    static void Entry(ZipArchive zip,string path,byte[] bytes) {
        using(var dest=zip.CreateEntry("Cadence/"+path).Open())dest.Write(bytes,0,bytes.Length);
    }
    static Package Build(MachineStore store,string candidate,RSACng signer,string marker="_internal-2.0.8\r\n") {
        using(var output=File.Create(store.Zip))
        using(var zip=new ZipArchive(output,ZipArchiveMode.Create)) {
            Entry(zip,"Cadence.exe",File.ReadAllBytes(candidate));
            Entry(zip,"_internal/layout.txt",Encoding.ASCII.GetBytes(marker));
            Entry(zip,"_internal-2.0.8/test.dll",new byte[]{2,0,8});
            Entry(zip,"Licences/notice.txt",Encoding.ASCII.GetBytes("new notice"));
        }
        var desc=new Package {Version="2.0.8",Size=new FileInfo(store.Zip).Length,Digest=Digest(store.Zip),Preview=true};
        desc.Signature=Convert.ToBase64String(signer.SignData(Encoding.ASCII.GetBytes(desc.Message()),HashAlgorithmName.SHA256,RSASignaturePadding.Pkcs1));
        return desc;
    }
    public static void Main(string[] args) {
        string scratch=Path.GetFullPath(args[0]);
        string product=Directory.CreateDirectory(Path.Combine(scratch,"Cadence")).FullName;
        bool restricted=RestrictProduct(product);
        string state=Directory.CreateDirectory(Path.Combine(scratch,"Private")).FullName;
        string exe=Path.Combine(product,"Cadence.exe"), candidate=Path.Combine(scratch,"candidate.exe");
        Executable(exe,"2.0.7");Executable(candidate,"2.0.8");
        if(restricted) {
            CheckRestricted(product,0x40,"No DELETE_CHILD permission on product root");
            CheckRestricted(exe,0x40000,"No WRITE_DAC permission on installed executable");
        }
        string old=Directory.CreateDirectory(Path.Combine(product,"_internal")).FullName;
        string known=Path.Combine(old,"previous.dll"), user=Path.Combine(old,"my-notes.txt"),locked=Path.Combine(old,"open.dat");
        string notices=Directory.CreateDirectory(Path.Combine(product,"Licences")).FullName;
        string notice=Path.Combine(notices,"notice.txt");
        File.WriteAllText(known,"old file"); File.WriteAllText(user,"personal file");File.WriteAllText(locked,"locked");File.WriteAllText(notice,"old notice");
        string receipt=Path.Combine(Directory.CreateDirectory(Path.Combine(product,"uninstall")).FullName,"installed-files.txt");
        File.WriteAllLines(receipt,new[]{Digest(known)+"|_internal/previous.dll",Digest(locked)+"|_internal/open.dat",Digest(notice)+"|Licences/notice.txt"});
        string runtime=Path.Combine(product,"_internal-2.0.8","test.dll");
        using(var signer=new RSACng(3072)) {
            var key=signer.ExportParameters(false);
            var store=new MachineStore(product,state,key,false);
            var desc=Build(store,candidate,signer);
            string signature=desc.Signature;
            byte[] invalid=Convert.FromBase64String(signature); invalid[0]^=1;desc.Signature=Convert.ToBase64String(invalid);
            Invalid(()=>store.Stage(desc),"Invalid signature refused");
            desc.Signature=signature;
            using(var file=File.OpenWrite(store.Zip))file.WriteByte(0);
            Invalid(()=>store.Stage(desc),"Changed downloaded bytes refused");
            desc=Build(store,candidate,signer,"_internal-2.0.9\n");
            Invalid(()=>store.Stage(desc),"Mismatched compatibility marker refused");
            desc=Build(store,candidate,signer);
            Check(desc.Digest==Digest(store.Zip),"Archive digest verified");
            store.Stage(desc);
            Check(store.State.Phase=="ready" && store.Installed()=="2.0.7" && !File.Exists(runtime),"Preparation preserves the running installation");
            File.WriteAllText(notice,"local changes");
            Invalid(()=>store.Apply(),"Conflicting local edits preserved");
            File.WriteAllText(notice,"old notice");
            using(var running=new FileStream(exe,FileMode.Open,FileAccess.Read,FileShare.Read)) {
                bool interrupted=false;
                try {store.Apply();} catch(System.ComponentModel.Win32Exception){interrupted=true;}
                Check(interrupted && store.State.Phase=="applying" && File.Exists(runtime),"Partial activation is journaled when executable is still mapped");
            }
            store=new MachineStore(product,state,key,false);
            store.Restore();
            Check(!File.Exists(runtime) && store.Installed()=="2.0.7" && File.ReadAllText(notice)=="old notice","Interrupted partial activation recovered");
            store.State.Failed="";store.Save();
            desc=Build(store,candidate,signer);store.Stage(desc);
            store.Apply();
            Check(store.State.Phase=="trial" && store.Installed()=="2.0.8" && File.Exists(runtime) && File.Exists(known),"Trial preserves fallback and activates candidate");
            var resumed=new MachineStore(product,state,key,false);
            resumed.Restore();
            Check(resumed.Installed()=="2.0.7" && !File.Exists(runtime) && File.Exists(known) && File.ReadAllText(notice)=="old notice",
                  "Recovery from disk restores original application and licence");
            desc=Build(resumed,candidate,signer);
            Invalid(()=>resumed.Stage(desc),"Previously rejected release excluded");
            resumed.State.Failed="";resumed.Save();
            resumed.Stage(desc);resumed.Apply();
            using(var handle=new FileStream(locked,FileMode.Open,FileAccess.Read,FileShare.None)) {
                resumed.State.Phase="confirming";resumed.Save();
                resumed=new MachineStore(product,state,key,false);resumed.Confirm();
                Check(resumed.State.Phase=="installed" && !File.Exists(known) && File.Exists(locked) && File.Exists(user),
                      "Confirmation resumes safely, defers locked files and preserves unrelated files");
            }
            resumed.Collect();
            Check(!File.Exists(locked) && File.Exists(user) && File.Exists(runtime),"Retry prunes only previous recorded runtime");
            File.WriteAllText(notice,"user edition");
            resumed.RemoveManaged();
            Check(!File.Exists(runtime) && File.Exists(user) && File.Exists(exe) && File.ReadAllText(notice)=="user edition",
                  "Uninstall removes managed artifacts and preserves user edits");
        }
    }
}

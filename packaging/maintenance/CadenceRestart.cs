// SPDX-License-Identifier: GPL-3.0-only
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Json;
using System.Security.Principal;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

internal static class CadenceRestart {
    const string Service = "CadenceStudio2Maintenance";
    const string Pipe = @"\\.\pipe\CadenceStudio2Maintenance.v1";
    [DllImport("advapi32", CharSet=CharSet.Unicode)] static extern IntPtr OpenSCManager(string computer, string database, uint access);
    [DllImport("advapi32", CharSet=CharSet.Unicode)] static extern IntPtr OpenService(IntPtr scm, string name, uint access);
    [DllImport("advapi32")] static extern bool QueryServiceStatusEx(IntPtr service, int info, [Out] uint[] result, int size, out int bytes);
    [DllImport("advapi32")] static extern bool CloseServiceHandle(IntPtr handle);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafePipeHandle CreateFile(string name, uint access, uint sharing, IntPtr security, uint mode, uint flags, IntPtr template);
    [DllImport("kernel32")] static extern bool GetNamedPipeServerProcessId(SafePipeHandle handle, out uint pid);

    static uint ServicePid() {
        IntPtr scm=OpenSCManager(null,null,1);
        if (scm==IntPtr.Zero) return 0;
        try {
            IntPtr service=OpenService(scm,Service,4);
            if (service==IntPtr.Zero) return 0;
            try {
                uint[] status=new uint[9]; int needed;
                return QueryServiceStatusEx(service,0,status,36,out needed) && status[1]==4 ? status[7] : 0;
            } finally { CloseServiceHandle(service); }
        } finally { CloseServiceHandle(scm); }
    }

    [DataContract] class Reply {
        [DataMember(Name="state")] public string State {get;set;}
    }

    static string Status() {
        uint service=ServicePid(), actual;
        if (service==0) return null;
        using (SafePipeHandle handle=CreateFile(Pipe,3,0,IntPtr.Zero,3,0x40110000,IntPtr.Zero)) {
            if (handle.IsInvalid || !GetNamedPipeServerProcessId(handle,out actual) || actual!=service) return null;
            using (var stream=new NamedPipeClientStream(PipeDirection.InOut,true,true,handle)) {
                var command=Encoding.ASCII.GetBytes("STATUS\n");
                if (!stream.WriteAsync(command,0,command.Length).Wait(2000)) return null;
                var reply=new byte[512]; int length=0;
                var elapsed=Stopwatch.StartNew();
                while (length<reply.Length && elapsed.ElapsedMilliseconds<3000) {
                    var read=stream.ReadAsync(reply,length,reply.Length-length);
                    if (!read.Wait(2000) || read.Result==0) return null;
                    length+=read.Result;
                    if (reply[length-1]==10) {
                        if (ServicePid()!=service) return null;
                        using (var json=new MemoryStream(reply,0,length))
                            return ((Reply)new DataContractJsonSerializer(typeof(Reply)).ReadObject(json)).State;
                    }
                }
            }
        }
        return null;
    }

    static int Main(string[] args) {
        if (args.Length!=0 || !Environment.Is64BitProcess) return 1;
        using (var identity=WindowsIdentity.GetCurrent())
            if (new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator)) return 1;
        string programFiles=Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        string folder=Path.Combine(programFiles,"Cadence 2.0");
        string app=Path.Combine(folder,"Cadence.exe");
        var elapsed=Stopwatch.StartNew();
        Process trial=null;
        while (elapsed.Elapsed.TotalMinutes<10) {
            string state=null;
            try { state=Status(); } catch (IOException) {} catch (AggregateException) {}
            catch (UnauthorizedAccessException) {} catch (SerializationException) {}
            bool fallback=state=="failed" || state==null && elapsed.Elapsed.TotalSeconds>60;
            if (trial!=null && (state=="installed" || fallback && !trial.HasExited)) return 0;
            if (state=="trial" && trial==null || state=="installed" || fallback ||
                (state=="idle" && elapsed.Elapsed.TotalSeconds>2) || (state=="waiting" && elapsed.Elapsed.TotalSeconds>60)) {
                try {
                    foreach (string path in new []{programFiles,folder,app})
                        if ((File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0) return 1;
                    var start=new ProcessStartInfo(app) { WorkingDirectory=folder, UseShellExecute=false };
                    if (state=="trial") {
                        start.EnvironmentVariables["CADENCE_MACHINE_TRIAL"]="1";
                        trial=Process.Start(start);
                    } else {
                        if (state=="failed" && trial!=null) start.EnvironmentVariables["CADENCE_MACHINE_RESTORED"]="1";
                        Process.Start(start);
                        return 0;
                    }
                } catch (IOException) {} catch (System.ComponentModel.Win32Exception) {}
            }
            Thread.Sleep(400);
        }
        return 1;
    }
}

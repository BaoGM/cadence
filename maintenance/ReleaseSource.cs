// SPDX-License-Identifier: GPL-3.0-only
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

namespace Cadence.Maintenance
{
    internal sealed class Package
    {
        internal static readonly Version MinimumVersion=new Version(2,0,8);
        internal string Version, Digest, Signature;
        internal long Size;
        internal bool Preview;

        internal static Version Number(string value)
        {
            if (value == null || !Regex.IsMatch(value, @"\A2\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\z"))
                throw new InvalidDataException("Invalid Studio version");
            return new Version(value);
        }

        internal string Message()
        {
            if(Number(Version)<MinimumVersion)throw new InvalidDataException("Release predates machine updates");
            if (Size <= 0 || Size > 2L * 1024 * 1024 * 1024 || Digest == null ||
                !Regex.IsMatch(Digest, @"\A[0-9a-f]{64}\z")) throw new InvalidDataException("Invalid package descriptor");
            return "Cadence/windows-x64/v1/" + (Preview ? "preview/" : "stable/") + Version + "/" +
                Size.ToString(CultureInfo.InvariantCulture) + "/" + Digest;
        }

        internal void Verify(RSAParameters key)
        {
            using (var rsa = new RSACng()) {
                rsa.ImportParameters(key);
                if (!rsa.VerifyData(Encoding.ASCII.GetBytes(Message()), Convert.FromBase64String(Signature),
                                    HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1)) throw new InvalidDataException("Invalid package signature");
            }
        }

        internal static RSAParameters Publisher()
        {
            using (var stream = typeof(Package).Assembly.GetManifestResourceStream("Cadence.Machine.UpdateKey"))
            using (var reader = new StreamReader(stream)) {
                byte[] bytes = Convert.FromBase64String(reader.ReadToEnd().Trim());
                if (bytes.Length != 411 || Encoding.ASCII.GetString(bytes, 0, 4) != "RSA1" ||
                    BitConverter.ToUInt32(bytes, 4) != 3072 || BitConverter.ToUInt32(bytes, 8) != 3 ||
                    BitConverter.ToUInt32(bytes, 12) != 384) throw new InvalidDataException("Publisher key");
                var key = new RSAParameters { Exponent = new byte[3], Modulus = new byte[384] };
                Buffer.BlockCopy(bytes, 24, key.Exponent, 0, 3);
                Buffer.BlockCopy(bytes, 27, key.Modulus, 0, 384);
                return key;
            }
        }
    }

    internal sealed class ReleaseSource
    {
        const string Repo = "https://github.com/BaoGM/cadence/releases/download/";
        const string Feed = "https://api.github.com/repos/BaoGM/cadence/releases?per_page=100";
        static readonly HashSet<string> Hosts = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
            "api.github.com","github.com","release-assets.githubusercontent.com","objects.githubusercontent.com" };
        internal static JavaScriptSerializer Json { get { return new JavaScriptSerializer { MaxJsonLength=4*1024*1024, RecursionLimit=32 }; } }
        static ReleaseSource() {
            ServicePointManager.SecurityProtocol=SecurityProtocolType.SystemDefault;
            ServicePointManager.CheckCertificateRevocationList=true;
        }

        static HttpWebResponse Open(string address)
        {
            var uri = new Uri(address);
            for (int i=0; i<6; i++) {
                if (uri.Scheme != Uri.UriSchemeHttps || !String.IsNullOrEmpty(uri.UserInfo) || uri.Port != 443 ||
                    !Hosts.Contains(uri.Host)) throw new InvalidDataException("Untrusted update source");
                var req = (HttpWebRequest)WebRequest.Create(uri);
                req.AllowAutoRedirect=false; req.Timeout=15000; req.ReadWriteTimeout=15000;
                req.UseDefaultCredentials=false; req.UserAgent="Cadence-Studio2-Maintenance";
                var res=(HttpWebResponse)req.GetResponse();
                if (res.StatusCode == HttpStatusCode.OK) return res;
                using (res) {
                    int code=(int)res.StatusCode;
                    if (code < 300 || code >= 400 || res.Headers["Location"] == null)
                        throw new InvalidDataException("Unexpected update response");
                    uri=new Uri(uri,res.Headers["Location"]);
                }
            }
            throw new InvalidDataException("Too many redirects");
        }
        static object Metadata(string address, int limit)
        {
            using (var response=Open(address))
            using (var input=response.GetResponseStream())
            using (var output=new MemoryStream()) {
                byte[] buffer=new byte[8192];
                var deadline=DateTime.UtcNow.AddSeconds(60);
                int count;
                while ((count=input.Read(buffer,0,buffer.Length)) > 0) {
                    if (output.Length+count > limit || DateTime.UtcNow > deadline) throw new InvalidDataException("Metadata limit");
                    output.Write(buffer,0,count);
                }
                return Json.DeserializeObject(new UTF8Encoding(false,true).GetString(output.ToArray()));
            }
        }
        static string Text(Dictionary<string,object> item, string name)
        {
            object value; return item.TryGetValue(name,out value) ? value as string : null;
        }
        static long Size(Dictionary<string,object> item, string name)
        {
            object value; if (!item.TryGetValue(name,out value) || !(value is int || value is long)) return -1;
            return Convert.ToInt64(value, CultureInfo.InvariantCulture);
        }
        internal Package Discover(string installed, bool previews, RSAParameters key)
        {
            Version best=Package.Number(installed); Package selected=null;
            foreach (var raw in (object[])Metadata(Feed,4*1024*1024)) {
                var item=raw as Dictionary<string,object>;
                if (item==null || !Object.Equals(item["draft"],false) || !(item["prerelease"] is bool)) continue;
                bool preview=(bool)item["prerelease"];
                if (preview && !previews) continue;
                string tag=Text(item,"tag_name") ?? "";
                var match=Regex.Match(tag,@"\Av(2\.(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3}))-windows-studio2\z");
                if (!match.Success) continue;
                string version=match.Groups[1].Value;
                if (Package.Number(version) <= best || Package.Number(version)<Package.MinimumVersion) continue;
                string assetName="Cadence-"+version+"-Windows.zip"; long bytes=-1; bool descriptor=false;
                foreach (var entry in (object[])item["assets"]) {
                    var asset=entry as Dictionary<string,object>;
                    if (asset==null || Text(asset,"state")!="uploaded") continue;
                    if (Text(asset,"name")==assetName) bytes=Size(asset,"size");
                    if (Text(asset,"name")=="Cadence-"+version+"-update.json") descriptor=true;
                }
                if (descriptor && bytes>0 && bytes<=2L*1024*1024*1024) {
                    selected=new Package { Version=version, Preview=preview, Size=bytes };
                    best=Package.Number(version);
                }
            }
            if (selected==null) return null;
            var desc=(Dictionary<string,object>)Metadata(Base(selected.Version)+"Cadence-"+selected.Version+"-update.json",65536);
            if (selected.Version!=Text(desc,"version") || selected.Size!=Size(desc,"size") || !Object.Equals(desc["preview"],selected.Preview))
                throw new InvalidDataException("Mismatched update descriptor");
            selected.Digest=Text(desc,"sha256"); selected.Signature=Text(desc,"signature");
            selected.Verify(key); return selected;
        }
        static string Base(string version) { Package.Number(version); return Repo+"v"+version+"-windows-studio2/"; }
        internal void Download(Package p,string destination, Action<int> progress, Func<bool> cancelled)
        {
            using (var response=Open(Base(p.Version)+"Cadence-"+p.Version+"-Windows.zip"))
            using (var input=response.GetResponseStream())
            using (var output=new FileStream(destination,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                var deadline=DateTime.UtcNow.AddMinutes(30); byte[] buffer=new byte[256*1024]; int n;
                while ((n=input.Read(buffer,0,buffer.Length))>0) {
                    if (cancelled() || DateTime.UtcNow>deadline || output.Length+n>p.Size) throw new IOException("Download interrupted");
                    output.Write(buffer,0,n); progress((int)(output.Length*100/p.Size));
                }
                output.Flush(true);
                if (output.Length!=p.Size) throw new InvalidDataException("Truncated update");
            }
        }
    }
}

// SPDX-License-Identifier: GPL-3.0-only
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <d3dcompiler.h>
#include <intrin.h>
#include <tmmintrin.h>
#include <array>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <memory>
#include <utility>
#include <vector>
#include <unordered_map>

#define CADENCE_D3D_API extern "C" __declspec(dllexport)

namespace {
template<class T> class ComPtr {
    T* value=nullptr;
public:
    ComPtr()=default;
    ComPtr(const ComPtr& other): value(other.value) { if (value) value->AddRef(); }
    ComPtr(ComPtr&& other) noexcept: value(std::exchange(other.value,nullptr)) {}
    ~ComPtr() { Reset(); }
    ComPtr& operator=(const ComPtr& other) {
        if (this!=std::addressof(other)) { T* next=other.value; if (next) next->AddRef(); Reset(); value=next; }
        return *this;
    }
    ComPtr& operator=(ComPtr&& other) noexcept {
        if (this!=std::addressof(other)) { Reset(); value=std::exchange(other.value,nullptr); }
        return *this;
    }
    T* Get() const { return value; }
    T* operator->() const { return value; }
    explicit operator bool() const { return value!=nullptr; }
    T** GetAddressOf() { return &value; }
    T** operator&() { Reset(); return &value; }
    void Reset() { if (value) { T* previous=value; value=nullptr; previous->Release(); } }
    template<class U> HRESULT As(ComPtr<U>* destination) {
        return value->QueryInterface(__uuidof(U),reinterpret_cast<void**>(destination->operator&()));
    }
};
thread_local char error_text[2048] = {};
struct Failure { HRESULT code; const char* operation; };
void check(HRESULT code, const char* operation) { if (FAILED(code)) throw Failure{code,operation}; }
int report(Failure error) noexcept {
    if (error.operation) std::snprintf(error_text,sizeof(error_text),"%s failed (0x%08lX)",error.operation,static_cast<unsigned long>(error.code));
    return 2;
}
struct Texture {
    ComPtr<ID3D11Texture2D> image;
    ComPtr<ID3D11ShaderResourceView> view;
    int width=0,height=0;
    uint64_t revision=0;
    uint64_t used=0;
};
struct DrawLayer {
    const uint8_t* pixels;
    int width,height;
    size_t stride;
    uint64_t revision;
    double quad[8];
    float opacity,clip[4];
};
struct Vertex { float x,y,u,v; };
struct Parameters {
    float width,height;
    int paired,passthrough,overlay;
    int layout=0,flip_h=0,flip_v=0;
    float b_width=0,b_height=0,wipe=.5f;
    int swapped=0;
    float alpha=1,compare_opacity=.5f,compare_gain=1,padding=0;
    float clip[4]={0,0,1,1};
};
struct Renderer {
    HWND window=nullptr;
    DWORD thread=0;
    bool capture=false,have_capture=false;
    int width=0,height=0,limit=0;
    char information[512] = {};
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    ComPtr<IDXGISwapChain1> swapchain;
    ComPtr<ID3D11Texture2D> backbuffer,staging;
    ComPtr<ID3D11RenderTargetView> target;
    ComPtr<ID3D11VertexShader> vertex_shader;
    ComPtr<ID3D11PixelShader> pixel_shader;
    ComPtr<ID3D11InputLayout> layout;
    ComPtr<ID3D11Buffer> vertices,parameters;
    ComPtr<ID3D11SamplerState> sampler;
    ComPtr<ID3D11BlendState> blend;
    ComPtr<ID3D11RasterizerState> rasterizer;
    ComPtr<ID3D11DepthStencilState> depth;
    std::array<Texture,4> textures;
    std::unordered_map<uint64_t,Texture> drawings;
    size_t drawing_bytes=0;
    uint64_t drawing_clock=0;
    uint64_t drawing_uploads=0;
    std::array<double,5> timings = {};
    ~Renderer() {
        if (context) { context->ClearState(); context->Flush(); }
        target.Reset(); backbuffer.Reset(); staging.Reset(); swapchain.Reset();
        if (context) context->Flush();
    }
};

const char* shader_source=R"(
cbuffer Parameters : register(b0) {
    float2 dimensions;
    int paired;
    int passthrough;
    int overlay;
    int layout; int flip_h; int flip_v;
    float2 b_dimensions; float wipe; int swapped;
    float alpha; float compare_opacity; float compare_gain; float padding;
    float4 annotation_clip;
};
Texture2D<float4> imageA : register(t0);
Texture2D<float4> imageB : register(t1);
Texture2D<float4> lookup : register(t2);
Texture2D<float4> annotation : register(t3);
SamplerState linearSampler : register(s0);
struct VertexInput { float2 position : POSITION; float2 uv : TEXCOORD0; };
struct PixelInput { float4 position : SV_POSITION; float2 uv : TEXCOORD0; };
PixelInput vertexMain(VertexInput input) {
    PixelInput output;
    output.position=float4(input.position,0,1);
    output.uv=input.uv;
    return output;
}
float channel(float a,float b) {
    int x=(int)floor((paired ? b : a)*255.0+0.5);
    int y=paired ? (int)floor(a*255.0+0.5) : 0;
    return lookup.Load(int3(x,y,0)).r;
}
float3 pixel(float2 location) {
    int2 texel=clamp((int2)location,int2(0,0),(int2)dimensions-1);
    float3 a=imageA.Load(int3(texel,0)).rgb;
    float3 b=paired ? imageB.Load(int3(texel,0)).rgb : float3(0,0,0);
    return float3(channel(a.r,b.r),channel(a.g,b.g),channel(a.b,b.b));
}

float3 chosenPixel(int2 texel,bool second) {
    int2 extent=(int2)(second ? b_dimensions : dimensions);
    texel=clamp(texel,int2(0,0),extent-1);
    float3 value=second ? imageB.Load(int3(texel,0)).rgb : imageA.Load(int3(texel,0)).rgb;
    return float3(channel(value.r,0),channel(value.g,0),channel(value.b,0));
}
float4 sampled(float2 uv,bool second) {
    if (second) {
        float2 fit=b_dimensions*min(dimensions.x/b_dimensions.x,dimensions.y/b_dimensions.y)/dimensions;
        uv=(uv-.5)/fit+.5;
        if (any(uv<0) || any(uv>1)) return float4(0,0,0,1);
    }
    if (passthrough) return float4(second ? imageB.Sample(linearSampler,uv).rgb : imageA.Sample(linearSampler,uv).rgb,1);
    float2 position=uv*(second ? b_dimensions : dimensions)-.5;
    int2 low=(int2)floor(position); float2 f=frac(position);
    float3 upper=lerp(chosenPixel(low,second),chosenPixel(low+int2(1,0),second),f.x);
    float3 lower=lerp(chosenPixel(low+int2(0,1),second),chosenPixel(low+int2(1,1),second),f.x);
    return float4(lerp(upper,lower,f.y),1);
}
float4 fittedPixel(float2 texel) {
    float2 location=(clamp(texel,float2(0.0,0.0),dimensions-1.0)+.5)/dimensions;
    float4 a=sampled(location,false),b=sampled(location,true);
    b=floor(b*255.0+.5)/255.0;
    if (layout==6) return float4(floor(min(abs(a.rgb-b.rgb)*compare_gain,float3(1,1,1))*255.0)/255.0,1.0);
    return floor(lerp(a,b,swapped!=0 ? 1.0-compare_opacity : compare_opacity)*255.0+.5)/255.0;
}
float4 spatial(float2 uv) {
    bool second=false;
    if (layout==1) { second=uv.x>=.5; uv.x=frac(uv.x*2); }
    else if (layout==2) { second=uv.y>=.5; uv.y=frac(uv.y*2); }
    else if (layout==3) second=uv.x>=wipe;
    second=second!=(swapped!=0);
    if (flip_h) uv.x=1-uv.x;
    if (flip_v) uv.y=1-uv.y;
    if (layout>=5) {
        float2 position=uv*dimensions-.5,low=floor(position),f=position-low;
        float4 upper=lerp(fittedPixel(low),fittedPixel(low+float2(1.0,0.0)),f.x);
        float4 lower=lerp(fittedPixel(low+float2(0.0,1.0)),fittedPixel(low+float2(1.0,1.0)),f.x);
        return lerp(upper,lower,f.y);
    }
    return sampled(uv,second);
}

float4 pixelMain(PixelInput input) : SV_TARGET {
    if (overlay) {
        if (any(input.uv<annotation_clip.xy) || any(input.uv>annotation_clip.zw)) discard;
        return annotation.Sample(linearSampler,input.uv)*alpha;
    }
    if (layout) return spatial(input.uv);
    if (passthrough) return float4(imageA.Sample(linearSampler,input.uv).rgb,1);
    float2 position=input.uv*dimensions-0.5;
    float2 low=floor(position),fraction=frac(position);
    float3 upper=lerp(pixel(low),pixel(low+float2(1,0)),fraction.x);
    float3 lower=lerp(pixel(low+float2(0,1)),pixel(low+float2(1,1)),fraction.x);
    return float4(lerp(upper,lower,fraction.y),1);
}
)";

ComPtr<ID3DBlob> compile(const char* entry,const char* target) {
    ComPtr<ID3DBlob> result,errors;
    const HRESULT code=D3DCompile(shader_source,std::strlen(shader_source),nullptr,nullptr,nullptr,entry,target,
        D3DCOMPILE_ENABLE_STRICTNESS|D3DCOMPILE_OPTIMIZATION_LEVEL3,0,&result,&errors);
    if (FAILED(code)) {
        std::snprintf(error_text,sizeof(error_text),"D3D shader compilation: %.*s",errors ? int(std::min<size_t>(errors->GetBufferSize(),1900)) : 0,
            errors ? static_cast<const char*>(errors->GetBufferPointer()) : "");
        throw Failure{code,nullptr};
    }
    return result;
}

bool adapter_matches(const wchar_t* name,const wchar_t* requested) {
    const size_t length=std::wcslen(name),match_length=std::wcslen(requested);
    if (match_length>length) return false;
    for (size_t offset=0;offset<=length-match_length;++offset)
        if (CompareStringOrdinal(name+offset,int(match_length),requested,int(match_length),TRUE)==CSTR_EQUAL) return true;
    return false;
}

bool display_adapter(HMONITOR monitor,LUID& adapter) {
    MONITORINFOEXW information={}; information.cbSize=sizeof(information);
    if (!GetMonitorInfoW(monitor,reinterpret_cast<MONITORINFO*>(&information))) return false;
    for (int attempt=0;attempt<3;++attempt) {
        UINT32 path_count=0,mode_count=0;
        if (GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS,&path_count,&mode_count)!=ERROR_SUCCESS) return false;
        if (!path_count || path_count>4096 || mode_count>16384) return false;
        std::vector<DISPLAYCONFIG_PATH_INFO> paths(path_count);
        std::vector<DISPLAYCONFIG_MODE_INFO> modes(mode_count);
        const LONG status=QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS,&path_count,paths.data(),&mode_count,modes.data(),nullptr);
        if (status==ERROR_INSUFFICIENT_BUFFER) continue;
        if (status!=ERROR_SUCCESS) return false;
        for (UINT32 index=0;index<path_count;++index) {
            const auto& path=paths[index];
            DISPLAYCONFIG_SOURCE_DEVICE_NAME source={};
            source.header.type=DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME; source.header.size=sizeof(source);
            source.header.adapterId=path.sourceInfo.adapterId; source.header.id=path.sourceInfo.id;
            if (DisplayConfigGetDeviceInfo(&source.header)==ERROR_SUCCESS &&
                CompareStringOrdinal(source.viewGdiDeviceName,-1,information.szDevice,-1,TRUE)==CSTR_EQUAL) {
                adapter=path.targetInfo.adapterId; return true;
            }
        }
        return false;
    }
    return false;
}

void initialize(Renderer& state) {
    ComPtr<IDXGIFactory2> factory;
    check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"CreateDXGIFactory1");
    ComPtr<IDXGIAdapter1> selected,output_selected;
    wchar_t requested[256]={};
    const DWORD requested_length=GetEnvironmentVariableW(L"CADENCE_D3D_ADAPTER",requested,256);
    if (requested_length>=256) {
        std::snprintf(error_text,sizeof(error_text),"CADENCE_D3D_ADAPTER is too long");
        throw Failure{E_INVALIDARG,nullptr};
    }
    const bool forced=requested_length>0;
    const HMONITOR monitor=MonitorFromWindow(state.window,MONITOR_DEFAULTTONEAREST);
    LUID physical_adapter={};
    const bool have_physical_adapter=!forced && display_adapter(monitor,physical_adapter);
    const char* selection=forced ? "forced" : "default";
    for (UINT index=0;!selected;++index) {
        ComPtr<IDXGIAdapter1> adapter;
        if (factory->EnumAdapters1(index,&adapter)==DXGI_ERROR_NOT_FOUND) break;
        if (!adapter) break;
        DXGI_ADAPTER_DESC1 description={}; adapter->GetDesc1(&description);
        if (description.Flags&DXGI_ADAPTER_FLAG_SOFTWARE) continue;
        if (forced) {
            if (adapter_matches(description.Description,requested)) selected=adapter;
            continue;
        }
        if (have_physical_adapter && description.AdapterLuid.HighPart==physical_adapter.HighPart &&
            description.AdapterLuid.LowPart==physical_adapter.LowPart) {
            selected=adapter; selection="physical-display"; break;
        }
        if (output_selected) continue;
        for (UINT output_index=0;;++output_index) {
            ComPtr<IDXGIOutput> output;
            if (adapter->EnumOutputs(output_index,&output)==DXGI_ERROR_NOT_FOUND || !output) break;
            DXGI_OUTPUT_DESC output_description={};
            if (SUCCEEDED(output->GetDesc(&output_description)) && output_description.Monitor==monitor) {
                output_selected=adapter; break;
            }
        }
        if (!have_physical_adapter && output_selected) { selected=output_selected; selection="dxgi-output"; }
    }
    if (!selected && output_selected) { selected=output_selected; selection="dxgi-output"; }
    if (forced && !selected) {
        char requested_utf8[768]={};
        WideCharToMultiByte(CP_UTF8,0,requested,-1,requested_utf8,sizeof(requested_utf8),nullptr,nullptr);
        std::snprintf(error_text,sizeof(error_text),"No hardware Direct3D adapter matches CADENCE_D3D_ADAPTER=%s",requested_utf8);
        throw Failure{DXGI_ERROR_NOT_FOUND,nullptr};
    }
    const D3D_FEATURE_LEVEL levels[]={D3D_FEATURE_LEVEL_11_0,D3D_FEATURE_LEVEL_10_1,D3D_FEATURE_LEVEL_10_0};
    D3D_FEATURE_LEVEL level;
    HRESULT created=D3D11CreateDevice(selected.Get(),selected ? D3D_DRIVER_TYPE_UNKNOWN : D3D_DRIVER_TYPE_HARDWARE,nullptr,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT,levels,3,D3D11_SDK_VERSION,&state.device,&level,&state.context);
    if (FAILED(created) && selected && !forced) {
        selected.Reset(); state.device.Reset(); state.context.Reset();
        selection="default-fallback";
        created=D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            levels,3,D3D11_SDK_VERSION,&state.device,&level,&state.context);
    }
    check(created,"D3D11CreateDevice");
    state.limit=level>=D3D_FEATURE_LEVEL_11_0 ? 16384 : 8192;
    ComPtr<IDXGIDevice1> dxgi_device; check(state.device.As(std::addressof(dxgi_device)),"Query DXGI device");
    ComPtr<IDXGIAdapter> adapter; check(dxgi_device->GetAdapter(&adapter),"GetAdapter");
    check(adapter->GetParent(IID_PPV_ARGS(&factory)),"Get DXGI factory");
    DXGI_ADAPTER_DESC description={}; check(adapter->GetDesc(&description),"Get adapter description");
    char adapter_name[256]={}; WideCharToMultiByte(CP_UTF8,0,description.Description,-1,adapter_name,sizeof(adapter_name),nullptr,nullptr);
    std::snprintf(state.information,sizeof(state.information),"adapter=%s; feature=0x%X; selection=%s; flip-sequential; interval=1",adapter_name,unsigned(level),selection);
    dxgi_device->SetMaximumFrameLatency(1);
    DXGI_SWAP_CHAIN_DESC1 swap={};
    swap.Width=1; swap.Height=1; swap.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    swap.SampleDesc.Count=1; swap.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;
    swap.BufferCount=2; swap.SwapEffect=DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
    swap.Scaling=DXGI_SCALING_STRETCH; swap.AlphaMode=DXGI_ALPHA_MODE_IGNORE;
    check(factory->CreateSwapChainForHwnd(state.device.Get(),state.window,&swap,nullptr,nullptr,&state.swapchain),"CreateSwapChainForHwnd");
    factory->MakeWindowAssociation(state.window,DXGI_MWA_NO_ALT_ENTER);
    const auto vertex=compile("vertexMain","vs_4_0"),pixel=compile("pixelMain","ps_4_0");
    check(state.device->CreateVertexShader(vertex->GetBufferPointer(),vertex->GetBufferSize(),nullptr,&state.vertex_shader),"CreateVertexShader");
    check(state.device->CreatePixelShader(pixel->GetBufferPointer(),pixel->GetBufferSize(),nullptr,&state.pixel_shader),"CreatePixelShader");
    const D3D11_INPUT_ELEMENT_DESC elements[]={
        {"POSITION",0,DXGI_FORMAT_R32G32_FLOAT,0,0,D3D11_INPUT_PER_VERTEX_DATA,0},
        {"TEXCOORD",0,DXGI_FORMAT_R32G32_FLOAT,0,8,D3D11_INPUT_PER_VERTEX_DATA,0}};
    check(state.device->CreateInputLayout(elements,2,vertex->GetBufferPointer(),vertex->GetBufferSize(),&state.layout),"CreateInputLayout");
    D3D11_BUFFER_DESC buffer={}; buffer.ByteWidth=sizeof(Vertex)*4; buffer.Usage=D3D11_USAGE_DYNAMIC;
    buffer.BindFlags=D3D11_BIND_VERTEX_BUFFER; buffer.CPUAccessFlags=D3D11_CPU_ACCESS_WRITE;
    check(state.device->CreateBuffer(&buffer,nullptr,&state.vertices),"Create vertex buffer");
    buffer.ByteWidth=sizeof(Parameters); buffer.BindFlags=D3D11_BIND_CONSTANT_BUFFER;
    check(state.device->CreateBuffer(&buffer,nullptr,&state.parameters),"Create constant buffer");
    D3D11_SAMPLER_DESC sampling={}; sampling.Filter=D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT;
    sampling.AddressU=sampling.AddressV=sampling.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;
    sampling.MaxLOD=D3D11_FLOAT32_MAX;
    check(state.device->CreateSamplerState(&sampling,&state.sampler),"CreateSamplerState");
    D3D11_BLEND_DESC blending={}; auto& blend=blending.RenderTarget[0];
    blend.BlendEnable=TRUE; blend.SrcBlend=D3D11_BLEND_ONE; blend.DestBlend=D3D11_BLEND_INV_SRC_ALPHA;
    blend.BlendOp=D3D11_BLEND_OP_ADD; blend.SrcBlendAlpha=D3D11_BLEND_ONE;
    blend.DestBlendAlpha=D3D11_BLEND_INV_SRC_ALPHA; blend.BlendOpAlpha=D3D11_BLEND_OP_ADD;
    blend.RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;
    check(state.device->CreateBlendState(&blending,&state.blend),"CreateBlendState");
    D3D11_RASTERIZER_DESC raster={}; raster.FillMode=D3D11_FILL_SOLID; raster.CullMode=D3D11_CULL_NONE; raster.DepthClipEnable=TRUE;
    check(state.device->CreateRasterizerState(&raster,&state.rasterizer),"CreateRasterizerState");
    D3D11_DEPTH_STENCIL_DESC depth={}; depth.DepthEnable=FALSE; depth.StencilEnable=FALSE;
    check(state.device->CreateDepthStencilState(&depth,&state.depth),"CreateDepthStencilState");
}

void resize(Renderer& state,int width,int height) {
    if (state.width==width && state.height==height && state.target) return;
    state.context->OMSetRenderTargets(0,nullptr,nullptr);
    state.target.Reset(); state.backbuffer.Reset(); state.staging.Reset(); state.have_capture=false;
    check(state.swapchain->ResizeBuffers(0,width,height,DXGI_FORMAT_UNKNOWN,0),"ResizeBuffers");
    check(state.swapchain->GetBuffer(0,IID_PPV_ARGS(&state.backbuffer)),"Get backbuffer");
    check(state.device->CreateRenderTargetView(state.backbuffer.Get(),nullptr,&state.target),"CreateRenderTargetView");
    if (state.capture) {
        D3D11_TEXTURE2D_DESC staging={}; state.backbuffer->GetDesc(&staging);
        staging.Usage=D3D11_USAGE_STAGING; staging.BindFlags=0; staging.CPUAccessFlags=D3D11_CPU_ACCESS_READ; staging.MiscFlags=0;
        check(state.device->CreateTexture2D(&staging,nullptr,&state.staging),"Create readback texture");
    }
    state.width=width; state.height=height;
}

void pack_bgra(const uint8_t* source,uint8_t* destination,int width) {
    static const bool shuffle_supported=[] { int registers[4]; __cpuid(registers,1); return (registers[2]&(1<<9))!=0; }();
    int x=0;
    if (shuffle_supported) {
        const auto mask=_mm_setr_epi8(2,1,0,-128,5,4,3,-128,8,7,6,-128,11,10,9,-128);
        const auto alpha=_mm_set1_epi32(static_cast<int>(0xff000000));
        for (;x+5<width;x+=4) {
            const auto value=_mm_loadu_si128(reinterpret_cast<const __m128i*>(source+x*3));
            _mm_storeu_si128(reinterpret_cast<__m128i*>(destination+x*4),_mm_or_si128(_mm_shuffle_epi8(value,mask),alpha));
        }
    }
    for (;x<width;++x) {
        destination[x*4]=source[x*3+2]; destination[x*4+1]=source[x*3+1];
        destination[x*4+2]=source[x*3]; destination[x*4+3]=255;
    }
}

void upload(Renderer& state,Texture& texture,const uint8_t* source,int width,int height,
            size_t stride,uint64_t revision,bool rgb,bool bgra=false) {
    if (texture.image && texture.width==width && texture.height==height && texture.revision==revision) return;
    if (!texture.image || texture.width!=width || texture.height!=height) {
        texture.view.Reset(); texture.image.Reset(); texture.revision=0;
        D3D11_TEXTURE2D_DESC description={}; description.Width=width; description.Height=height;
        description.MipLevels=description.ArraySize=description.SampleDesc.Count=1;
        description.Format=(rgb || bgra) ? DXGI_FORMAT_B8G8R8A8_UNORM : DXGI_FORMAT_R8G8B8A8_UNORM;
        description.Usage=D3D11_USAGE_DYNAMIC; description.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        description.CPUAccessFlags=D3D11_CPU_ACCESS_WRITE;
        check(state.device->CreateTexture2D(&description,nullptr,&texture.image),"Create image texture");
        check(state.device->CreateShaderResourceView(texture.image.Get(),nullptr,&texture.view),"CreateShaderResourceView");
        texture.width=width; texture.height=height;
    }
    D3D11_MAPPED_SUBRESOURCE mapped={};
    check(state.context->Map(texture.image.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped),"Map image texture");
    for (int y=0;y<height;++y) {
        auto* row=static_cast<uint8_t*>(mapped.pData)+size_t(y)*mapped.RowPitch;
        if (rgb) pack_bgra(source+size_t(y)*stride,row,width);
        else std::memcpy(row,source+size_t(y)*stride,size_t(width)*4);
    }
    state.context->Unmap(texture.image.Get(),0); texture.revision=revision;
}

void draw(Renderer& state,const double* quad,bool flip_h,bool flip_v,const Parameters& parameters) {
    D3D11_MAPPED_SUBRESOURCE mapped={};
    check(state.context->Map(state.vertices.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped),"Map vertices");
    auto* vertices=static_cast<Vertex*>(mapped.pData);
    for (int index=0;index<4;++index) vertices[index]={
        float(quad[index*2]*2/state.width-1),float(1-quad[index*2+1]*2/state.height),
        float((index%2)^int(flip_h)),float((index/2)^int(flip_v))};
    state.context->Unmap(state.vertices.Get(),0);
    check(state.context->Map(state.parameters.Get(),0,D3D11_MAP_WRITE_DISCARD,0,&mapped),"Map constants");
    std::memcpy(mapped.pData,&parameters,sizeof(parameters)); state.context->Unmap(state.parameters.Get(),0);
    state.context->PSSetConstantBuffers(0,1,state.parameters.GetAddressOf());
    state.context->OMSetBlendState(parameters.overlay ? state.blend.Get() : nullptr,nullptr,0xffffffff);
    state.context->Draw(4,0);
}
}

CADENCE_D3D_API int cadence_d3d_abi() noexcept { return 3; }
CADENCE_D3D_API const char* cadence_d3d_error() noexcept { return error_text; }
CADENCE_D3D_API const char* cadence_d3d_info(void* handle) noexcept {
    return handle ? static_cast<Renderer*>(handle)->information : "No Direct3D renderer";
}
CADENCE_D3D_API void* cadence_d3d_create(void* window,int readback) noexcept {
    try {
        const HWND hwnd=static_cast<HWND>(window);
        if (!IsWindow(hwnd) || GetWindowThreadProcessId(hwnd,nullptr)!=GetCurrentThreadId()) {
            std::snprintf(error_text,sizeof(error_text),"Direct3D requires a native window on the current thread"); return nullptr;
        }
        auto state=std::make_unique<Renderer>(); state->window=hwnd; state->thread=GetCurrentThreadId(); state->capture=readback!=0;
        initialize(*state); return state.release();
    } catch (Failure error) { report(error); return nullptr; }
    catch (...) { std::snprintf(error_text,sizeof(error_text),"Direct3D initialization failed"); return nullptr; }
}
CADENCE_D3D_API void cadence_d3d_destroy(void* handle) noexcept { delete static_cast<Renderer*>(handle); }
CADENCE_D3D_API void cadence_d3d_timings(void* handle,double* values) noexcept {
    if (handle && values) std::copy(static_cast<Renderer*>(handle)->timings.begin(),static_cast<Renderer*>(handle)->timings.end(),values);
}
CADENCE_D3D_API void cadence_d3d_drawing_stats(void* handle,uint64_t* values) noexcept {
    if (!handle || !values) return;
    auto* state=static_cast<Renderer*>(handle);
    values[0]=state->drawing_bytes; values[1]=state->drawings.size(); values[2]=state->drawing_uploads;
}
CADENCE_D3D_API int cadence_d3d_paint(void* handle,const uint8_t* a,const uint8_t* b,int width,int height,
    const uint8_t* lookup,int table_height,uint64_t a_revision,uint64_t b_revision,uint64_t table_revision,
    const double* quad,int flip_h,int flip_v,int passthrough,const uint8_t* overlay,size_t overlay_stride,
    uint64_t overlay_revision,int viewport_width,int viewport_height,int b_width,int b_height,int layout,int swapped,float wipe,const DrawLayer* layers,int layer_count,float compare_opacity,float compare_gain) noexcept {
    auto* state=static_cast<Renderer*>(handle);
    if (!state || state->thread!=GetCurrentThreadId() || !IsWindow(state->window)) return 1;
    if (viewport_width<=0 || viewport_height<=0 || viewport_width>state->limit || viewport_height>state->limit ||
        (overlay && overlay_stride<size_t(viewport_width)*4)) return 1;
    if (a && (!quad || !lookup || width<=0 || height<=0 || width>state->limit || height>state->limit ||
        (table_height!=1 && table_height!=256) || (table_height==256 && !b))) return 1;
    if (layout<0 || layout>6 || !std::isfinite(wipe) || !std::isfinite(compare_opacity) || !std::isfinite(compare_gain) || (layout && !b) ||
        (b && (b_width<=0 || b_height<=0 || b_width>state->limit || b_height>state->limit))) return 1;
    if (a) for (int i=0;i<8;++i) if (!std::isfinite(quad[i])) return 1;
    if (layer_count<0 || layer_count>4096 || (layer_count && !layers)) return 1;
    for (int i=0;i<layer_count;++i) {
        const auto& layer=layers[i];
        if (!layer.pixels || layer.width<=0 || layer.height<=0 || layer.width>state->limit || layer.height>state->limit ||
            layer.stride<size_t(layer.width)*4 || !std::isfinite(layer.opacity) || layer.opacity<0 || layer.opacity>1) return 1;
        for (double value:layer.quad) if (!std::isfinite(value)) return 1;
        for (float value:layer.clip) if (!std::isfinite(value) || value<0 || value>1) return 1;
    }
    try {
        using Clock=std::chrono::steady_clock;
        auto stamp=Clock::now();
        auto phase=[&](int index) { const auto now=Clock::now(); state->timings[index]=std::chrono::duration<double,std::milli>(now-stamp).count(); stamp=now; };
        resize(*state,viewport_width,viewport_height);
        ID3D11ShaderResourceView* empty[4]={}; state->context->PSSetShaderResources(0,4,empty);
        phase(0);
        if (a) {
            upload(*state,state->textures[0],a,width,height,size_t(width)*3,a_revision,true);
            if (b) upload(*state,state->textures[1],b,b_width,b_height,size_t(b_width)*3,b_revision,true);
            else state->textures[1].revision=0;
            upload(*state,state->textures[2],lookup,256,table_height,256*4,table_revision,false);
        } else { state->textures[0].revision=0; state->textures[1].revision=0; state->textures[2].revision=0; }
        phase(1);
        if (overlay) upload(*state,state->textures[3],overlay,viewport_width,viewport_height,overlay_stride,overlay_revision,false);
        else state->textures[3].revision=0;
        phase(2);
        const float background[]={12/255.f,15/255.f,20/255.f,1.f};
        state->context->ClearRenderTargetView(state->target.Get(),background);
        state->context->OMSetRenderTargets(1,state->target.GetAddressOf(),nullptr);
        D3D11_VIEWPORT viewport={0,0,float(viewport_width),float(viewport_height),0,1}; state->context->RSSetViewports(1,&viewport);
        state->context->RSSetState(state->rasterizer.Get()); state->context->OMSetDepthStencilState(state->depth.Get(),0);
        state->context->IASetInputLayout(state->layout.Get()); state->context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP);
        const UINT stride=sizeof(Vertex),offset=0; state->context->IASetVertexBuffers(0,1,state->vertices.GetAddressOf(),&stride,&offset);
        state->context->VSSetShader(state->vertex_shader.Get(),nullptr,0); state->context->PSSetShader(state->pixel_shader.Get(),nullptr,0);
        state->context->PSSetSamplers(0,1,state->sampler.GetAddressOf());
        ID3D11ShaderResourceView* views[4]={}; for(int i=0;i<4;++i) views[i]=state->textures[i].view.Get();
        state->context->PSSetShaderResources(0,4,views);
        if (a) { Parameters parameters={float(width),float(height),table_height==256,passthrough!=0,0,layout,flip_h,flip_v,float(b_width),float(b_height),wipe,swapped}; parameters.compare_opacity=compare_opacity; parameters.compare_gain=compare_gain; draw(*state,quad,layout ? false : flip_h!=0,layout ? false : flip_v!=0,parameters); }
        constexpr size_t drawing_budget=256*1024*1024;
        for (int i=0;i<layer_count;++i) {
            const auto& layer=layers[i];
            const size_t bytes=size_t(layer.width)*layer.height*4;
            auto found=state->drawings.find(layer.revision);
            Texture transient;
            Texture* texture=&transient;
            if (found!=state->drawings.end()) texture=&found->second;
            else if (bytes<=drawing_budget) {
                while (!state->drawings.empty() && (state->drawing_bytes+bytes>drawing_budget || state->drawings.size()>=256)) {
                    auto oldest=std::min_element(state->drawings.begin(),state->drawings.end(),[](const auto& x,const auto& y){return x.second.used<y.second.used;});
                    state->drawing_bytes-=size_t(oldest->second.width)*oldest->second.height*4;
                    state->drawings.erase(oldest);
                }
                texture=&state->drawings[layer.revision]; state->drawing_bytes+=bytes;
            }
            ID3D11ShaderResourceView* empty_view=nullptr; state->context->PSSetShaderResources(3,1,&empty_view);
            if (!texture->image || texture->revision!=layer.revision) ++state->drawing_uploads;
            upload(*state,*texture,layer.pixels,layer.width,layer.height,layer.stride,layer.revision,false,true);
            texture->used=++state->drawing_clock;
            state->context->PSSetShaderResources(3,1,texture->view.GetAddressOf());
            Parameters parameters={float(layer.width),float(layer.height),0,0,1};
            parameters.alpha=layer.opacity; std::copy(std::begin(layer.clip),std::end(layer.clip),parameters.clip);
            draw(*state,layer.quad,false,false,parameters);
        }
        if (overlay) {
            state->context->PSSetShaderResources(3,1,state->textures[3].view.GetAddressOf());
            const double overlay_quad[]={0,0,double(viewport_width),0,0,double(viewport_height),double(viewport_width),double(viewport_height)};
            Parameters parameters={float(viewport_width),float(viewport_height),0,0,1}; draw(*state,overlay_quad,false,false,parameters);
        }
        if (state->capture) { state->context->CopyResource(state->staging.Get(),state->backbuffer.Get()); state->have_capture=true; }
        phase(3);
        check(state->swapchain->Present(1,0),"Present"); phase(4);
        return 0;
    } catch (Failure error) { return report(error); }
    catch (...) { std::snprintf(error_text,sizeof(error_text),"Direct3D painting failed"); return 3; }
}
CADENCE_D3D_API int cadence_d3d_readback(void* handle,uint8_t* output,size_t stride,int width,int height) noexcept {
    auto* state=static_cast<Renderer*>(handle);
    if (!state || state->thread!=GetCurrentThreadId() || !state->capture || !state->have_capture || !output ||
        width!=state->width || height!=state->height || stride<size_t(width)*4) return 1;
    try {
        D3D11_MAPPED_SUBRESOURCE mapped={}; check(state->context->Map(state->staging.Get(),0,D3D11_MAP_READ,0,&mapped),"Map readback");
        for(int y=0;y<height;++y) {
            const auto* source=static_cast<const uint8_t*>(mapped.pData)+size_t(y)*mapped.RowPitch;
            auto* destination=output+size_t(y)*stride;
            for(int x=0;x<width;++x) {
                destination[x*4]=source[x*4+2]; destination[x*4+1]=source[x*4+1];
                destination[x*4+2]=source[x*4]; destination[x*4+3]=source[x*4+3];
            }
        }
        state->context->Unmap(state->staging.Get(),0); return 0;
    } catch (Failure error) { return report(error); }
    catch (...) { std::snprintf(error_text,sizeof(error_text),"Direct3D readback failed"); return 3; }
}

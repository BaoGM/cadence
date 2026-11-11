// SPDX-License-Identifier: GPL-3.0-only
#include <QtCore/QPointer>
#include <QtCore/QtGlobal>
#include <QtCore/QDebug>
#include <QtGui/QOpenGLContext>
#include <QtGui/QOpenGLFunctions>
#include <QtGui/QOpenGLExtraFunctions>
#include <QtGui/QPainter>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <chrono>
#include <cstring>
#include <memory>
#include <string>

#define CADENCE_API extern "C" Q_DECL_EXPORT

namespace {
thread_local std::string failure;
thread_local std::array<double, 5> timings;
using Clock = std::chrono::steady_clock;

struct Texture {
    GLuint id = 0;
    int width = 0, height = 0;
    uint64_t revision = 0;
    GLuint unpack_buffer = 0;
    bool buffer_failed = false;
};

struct Compositor {
    QPointer<QOpenGLContext> context;
    GLuint program = 0, vertices = 0;
    std::array<Texture, 3> textures;
    GLint dimensions = -1, pair = -1, passthrough = -1;
    bool profile = false, buffered_upload = false;
};

GLuint shader(QOpenGLFunctions* gl, GLenum type, const std::string& source)
{
    const GLuint id = gl->glCreateShader(type);
    const char* code = source.c_str();
    gl->glShaderSource(id, 1, &code, nullptr);
    gl->glCompileShader(id);
    GLint success = 0;
    gl->glGetShaderiv(id, GL_COMPILE_STATUS, &success);
    if (!success) {
        char message[2048] = {};
        gl->glGetShaderInfoLog(id, sizeof(message) - 1, nullptr, message);
        failure = message;
        gl->glDeleteShader(id);
        return 0;
    }
    return id;
}

void release(Compositor& state, QOpenGLFunctions* gl)
{
    for (auto& texture : state.textures) {
        if (texture.id) gl->glDeleteTextures(1, &texture.id);
        if (texture.unpack_buffer) gl->glDeleteBuffers(1, &texture.unpack_buffer);
        texture = {};
    }
    if (state.vertices) gl->glDeleteBuffers(1, &state.vertices);
    if (state.program) gl->glDeleteProgram(state.program);
    state.vertices = state.program = 0;
}

bool initialize(Compositor& state, QOpenGLFunctions* gl)
{
    auto* context = state.context.data();
    const bool modern = context->format().profile() == QSurfaceFormat::CoreProfile;
    // Desktop compatibility and ES 2 shaders share the same attribute/varying form.
    const std::string header = modern ? "#version 150\n" :
        (context->isOpenGLES() ? "#version 100\nprecision highp float;\n" : "#version 120\n");
    const std::string vertex = header +
        (modern ? "in vec2 position; in vec2 texcoord; out vec2 uv;\n" :
                  "attribute vec2 position; attribute vec2 texcoord; varying vec2 uv;\n") +
        "void main() { uv = texcoord; gl_Position = vec4(position, 0.0, 1.0); }\n";
    const std::string fragment = header +
        (modern ? "in vec2 uv; out vec4 outputColor;\n#define SAMPLE texture\n#define OUTPUT outputColor\n" :
                  "varying vec2 uv;\n#define SAMPLE texture2D\n#define OUTPUT gl_FragColor\n") + R"(
uniform sampler2D imageA;
uniform sampler2D imageB;
uniform sampler2D lookup;
uniform vec2 dimensions;
uniform bool paired;
uniform bool passthrough;
uniform int layout;
uniform vec2 b_dimensions;
uniform bool flipped_h,flipped_v,swapped;
uniform float wipe,compare_opacity,compare_gain;
float channel(float a, float b) {
    float x = paired ? floor(b * 255.0 + 0.5) : floor(a * 255.0 + 0.5);
    float y = paired ? floor(a * 255.0 + 0.5) : 0.0;
    return SAMPLE(lookup, vec2((x + 0.5) / 256.0, paired ? (y + 0.5) / 256.0 : 0.5)).r;
}
vec3 pixel(vec2 location) {
    vec2 coordinate = (location + 0.5) / dimensions;
    vec3 a = SAMPLE(imageA, coordinate).rgb;
    vec3 b = paired ? SAMPLE(imageB, coordinate).rgb : vec3(0.0);
    return vec3(channel(a.r,b.r), channel(a.g,b.g), channel(a.b,b.b));
}

vec3 chosenPixel(vec2 texel,bool second) {
    vec2 extent=second ? b_dimensions : dimensions;
    vec2 coordinate=(texel+.5)/extent;
    vec3 value=second ? SAMPLE(imageB,coordinate).rgb : SAMPLE(imageA,coordinate).rgb;
    return vec3(channel(value.r,0.0),channel(value.g,0.0),channel(value.b,0.0));
}
vec4 sampled(vec2 point,bool second) {
    if (second) {
        vec2 fit=b_dimensions*min(dimensions.x/b_dimensions.x,dimensions.y/b_dimensions.y)/dimensions;
        point=(point-.5)/fit+.5;
        if (any(lessThan(point,vec2(0.0))) || any(greaterThan(point,vec2(1.0)))) return vec4(0.0,0.0,0.0,1.0);
    }
    if (passthrough) return vec4(second ? SAMPLE(imageB,point).rgb : SAMPLE(imageA,point).rgb,1.0);
    vec2 position=point*(second ? b_dimensions : dimensions)-.5;
    vec2 low=floor(position),f=fract(position);
    vec3 upper=mix(chosenPixel(low,second),chosenPixel(low+vec2(1.0,0.0),second),f.x);
    vec3 lower=mix(chosenPixel(low+vec2(0.0,1.0),second),chosenPixel(low+vec2(1.0,1.0),second),f.x);
    return vec4(mix(upper,lower,f.y),1.0);
}
vec4 fittedPixel(vec2 texel) {
    vec2 location=(clamp(texel,vec2(0.0,0.0),dimensions-1.0)+.5)/dimensions;
    vec4 a=sampled(location,false),b=sampled(location,true);
    b=floor(b*255.0+.5)/255.0;
    if (layout==6) return vec4(floor(min(abs(a.rgb-b.rgb)*compare_gain,vec3(1.0))*255.0)/255.0,1.0);
    return floor(mix(a,b,swapped ? 1.0-compare_opacity : compare_opacity)*255.0+.5)/255.0;
}
vec4 spatial(vec2 point) {
    bool second=false;
    if (layout==1) { second=point.x>=.5; point.x=fract(point.x*2.0); }
    else if (layout==2) { second=point.y>=.5; point.y=fract(point.y*2.0); }
    else if (layout==3) second=point.x>=wipe;
    second=second!=swapped;
    if (flipped_h) point.x=1.0-point.x;
    if (flipped_v) point.y=1.0-point.y;
    if (layout>=5) {
        vec2 position=point*dimensions-.5,low=floor(position),f=position-low;
        vec4 upper=mix(fittedPixel(low),fittedPixel(low+vec2(1.0,0.0)),f.x);
        vec4 lower=mix(fittedPixel(low+vec2(0.0,1.0)),fittedPixel(low+vec2(1.0,1.0)),f.x);
        return mix(upper,lower,f.y);
    }
    return sampled(point,second);
}

void main() {
    if (layout!=0) { OUTPUT=spatial(uv); return; }
    if (passthrough) { OUTPUT = vec4(SAMPLE(imageA, uv).rgb, 1.0); return; }
    vec2 position = uv * dimensions - 0.5;
    vec2 low = floor(position);
    vec2 fraction = fract(position);
    vec3 upper = mix(pixel(low), pixel(low + vec2(1.0,0.0)), fraction.x);
    vec3 lower = mix(pixel(low + vec2(0.0,1.0)), pixel(low + vec2(1.0,1.0)), fraction.x);
    OUTPUT = vec4(mix(upper, lower, fraction.y), 1.0);
}
)";
    GLuint vertex_id = shader(gl, GL_VERTEX_SHADER, vertex);
    if (!vertex_id) return false;
    GLuint fragment_id = shader(gl, GL_FRAGMENT_SHADER, fragment);
    if (!fragment_id) { gl->glDeleteShader(vertex_id); return false; }
    state.program = gl->glCreateProgram();
    gl->glAttachShader(state.program, vertex_id);
    gl->glAttachShader(state.program, fragment_id);
    gl->glBindAttribLocation(state.program, 0, "position");
    gl->glBindAttribLocation(state.program, 1, "texcoord");
    gl->glLinkProgram(state.program);
    gl->glDeleteShader(vertex_id); gl->glDeleteShader(fragment_id);
    GLint success = 0;
    gl->glGetProgramiv(state.program, GL_LINK_STATUS, &success);
    if (!success) {
        char message[2048] = {};
        gl->glGetProgramInfoLog(state.program, sizeof(message) - 1, nullptr, message);
        failure = message; release(state, gl); return false;
    }
    state.dimensions = gl->glGetUniformLocation(state.program, "dimensions");
    state.pair = gl->glGetUniformLocation(state.program, "paired");
    state.passthrough = gl->glGetUniformLocation(state.program, "passthrough");
    gl->glGenBuffers(1, &state.vertices);
    for (auto& texture : state.textures) gl->glGenTextures(1, &texture.id);
    return true;
}

void upload(QOpenGLFunctions* gl, Texture& texture, const uint8_t* data,
            int width, int height, GLenum format, uint64_t revision, bool buffered = false)
{
    gl->glBindTexture(GL_TEXTURE_2D, texture.id);
    gl->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    gl->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    gl->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    gl->glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    const bool resize = texture.width != width || texture.height != height;
    const bool changed = resize || texture.revision != revision;
    if (buffered && !texture.buffer_failed && changed) {
        auto* extra = QOpenGLContext::currentContext()->extraFunctions();
        const size_t bytes = size_t(width)*height*3;
        if (!texture.unpack_buffer) gl->glGenBuffers(1,&texture.unpack_buffer);
        gl->glBindBuffer(GL_PIXEL_UNPACK_BUFFER,texture.unpack_buffer);
        gl->glBufferData(GL_PIXEL_UNPACK_BUFFER,bytes,nullptr,GL_STREAM_DRAW);
        void* mapped=extra->glMapBufferRange(GL_PIXEL_UNPACK_BUFFER,0,bytes,GL_MAP_WRITE_BIT|GL_MAP_INVALIDATE_BUFFER_BIT);
        if (mapped) {
            std::memcpy(mapped,data,bytes);
            if (extra->glUnmapBuffer(GL_PIXEL_UNPACK_BUFFER)) data=nullptr;
        }
        if (data) {
            const GLenum error=gl->glGetError();
            gl->glBindBuffer(GL_PIXEL_UNPACK_BUFFER,0);
            gl->glDeleteBuffers(1,&texture.unpack_buffer); texture.unpack_buffer=0;
            texture.buffer_failed=true;
            qWarning("GPU buffered upload failed (%u); using direct upload",unsigned(error));
        }
    }
    if (resize) {
        gl->glTexImage2D(GL_TEXTURE_2D, 0, format, width, height, 0, format, GL_UNSIGNED_BYTE, data);
        texture.width = width; texture.height = height;
    } else if (changed) {
        gl->glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, width, height, format, GL_UNSIGNED_BYTE, data);
    }
    texture.revision = revision;
    if (buffered) gl->glBindBuffer(GL_PIXEL_UNPACK_BUFFER,0);
}

struct NativeScope {
    QPainter* painter;
    QOpenGLFunctions* gl;
    GLint program, buffer, active, alignment, row_length = 0, skip_rows = 0, skip_pixels = 0, unpack_buffer = 0;
    bool unpack_supported;
    bool extended_unpack;
    std::array<GLint, 3> bindings;
    GLboolean blend, depth, cull, scissor, stencil;
    explicit NativeScope(QPainter* value, QOpenGLFunctions* functions) : painter(value), gl(functions) {
        painter->beginNativePainting();
        gl->glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        gl->glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &buffer);
        gl->glGetIntegerv(GL_ACTIVE_TEXTURE, &active);
        gl->glGetIntegerv(GL_UNPACK_ALIGNMENT, &alignment);
        const auto* context = QOpenGLContext::currentContext();
        unpack_supported = context->format().majorVersion()>=3;
        if (unpack_supported) {
            gl->glGetIntegerv(GL_PIXEL_UNPACK_BUFFER_BINDING,&unpack_buffer);
            gl->glBindBuffer(GL_PIXEL_UNPACK_BUFFER,0);
        }
        extended_unpack = !context->isOpenGLES() || context->format().majorVersion() >= 3;
        if (extended_unpack) {
            gl->glGetIntegerv(GL_UNPACK_ROW_LENGTH, &row_length);
            gl->glGetIntegerv(GL_UNPACK_SKIP_ROWS, &skip_rows);
            gl->glGetIntegerv(GL_UNPACK_SKIP_PIXELS, &skip_pixels);
            gl->glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
            gl->glPixelStorei(GL_UNPACK_SKIP_ROWS, 0);
            gl->glPixelStorei(GL_UNPACK_SKIP_PIXELS, 0);
        }
        for (int i = 0; i < 3; ++i) {
            gl->glActiveTexture(GL_TEXTURE0 + i);
            gl->glGetIntegerv(GL_TEXTURE_BINDING_2D, &bindings[i]);
        }
        blend = gl->glIsEnabled(GL_BLEND); depth = gl->glIsEnabled(GL_DEPTH_TEST);
        cull = gl->glIsEnabled(GL_CULL_FACE); scissor = gl->glIsEnabled(GL_SCISSOR_TEST);
        stencil = gl->glIsEnabled(GL_STENCIL_TEST);
        gl->glDisable(GL_BLEND); gl->glDisable(GL_DEPTH_TEST); gl->glDisable(GL_CULL_FACE);
        gl->glDisable(GL_SCISSOR_TEST); gl->glDisable(GL_STENCIL_TEST);
        gl->glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    }
    ~NativeScope() {
        gl->glDisableVertexAttribArray(0); gl->glDisableVertexAttribArray(1);
        gl->glBindBuffer(GL_ARRAY_BUFFER, buffer);
        gl->glUseProgram(program);
        for (int i = 0; i < 3; ++i) {
            gl->glActiveTexture(GL_TEXTURE0 + i); gl->glBindTexture(GL_TEXTURE_2D, bindings[i]);
        }
        gl->glActiveTexture(active); gl->glPixelStorei(GL_UNPACK_ALIGNMENT, alignment);
        if (extended_unpack) {
            gl->glPixelStorei(GL_UNPACK_ROW_LENGTH, row_length);
            gl->glPixelStorei(GL_UNPACK_SKIP_ROWS, skip_rows);
            gl->glPixelStorei(GL_UNPACK_SKIP_PIXELS, skip_pixels);
        }
        if (unpack_supported) gl->glBindBuffer(GL_PIXEL_UNPACK_BUFFER,unpack_buffer);
        auto restore = [this](GLenum capability, bool enabled) {
            if (enabled) gl->glEnable(capability); else gl->glDisable(capability);
        };
        restore(GL_BLEND,blend); restore(GL_DEPTH_TEST,depth); restore(GL_CULL_FACE,cull);
        restore(GL_SCISSOR_TEST,scissor); restore(GL_STENCIL_TEST,stencil);
        painter->endNativePainting();
    }
};
}

CADENCE_API int cadence_gpu_abi() noexcept { return 3; }
CADENCE_API const char* cadence_gpu_error() noexcept { return failure.c_str(); }
CADENCE_API void cadence_gpu_timings(double* output) noexcept
{
    if (output) std::copy(timings.begin(),timings.end(),output);
}
CADENCE_API const char* cadence_gpu_info() noexcept
{
    try {
        static thread_local std::string information;
        auto* context = QOpenGLContext::currentContext();
        if (!context) return "No current OpenGL context";
        auto* gl = context->functions();
        const auto value = [gl](GLenum name) {
            const auto* text = gl->glGetString(name);
            return text ? reinterpret_cast<const char*>(text) : "unavailable";
        };
        information = "vendor=" + std::string(value(GL_VENDOR)) +
            "; renderer=" + value(GL_RENDERER) + "; version=" + value(GL_VERSION);
        return information.c_str();
    } catch (...) { return "GPU information unavailable"; }
}

CADENCE_API void* cadence_gpu_create() noexcept
{
    try {
        auto* context = QOpenGLContext::currentContext();
        if (!context || context->format().majorVersion() < 2) return nullptr;
        // QPainter's default compatibility context needs no VAO; core contexts use the CPU fallback.
        if (context->format().profile() == QSurfaceFormat::CoreProfile) return nullptr;
        auto state = std::make_unique<Compositor>(); state->context = context;
        state->profile = qEnvironmentVariableIsSet("CADENCE_GPU_PROFILE");
        const auto upload = qEnvironmentVariable("CADENCE_GPU_UPLOAD");
        state->buffered_upload = context->format().majorVersion()>=3 && upload!="rgb" && upload!="direct";
        return state.release();
    } catch (...) { failure = "GPU compositor allocation failed"; return nullptr; }
}

CADENCE_API int cadence_gpu_destroy(void* handle) noexcept
{
    auto* state = static_cast<Compositor*>(handle);
    if (!state) return 0;
    if (state->context && state->context != QOpenGLContext::currentContext()) return 1;
    if (state->context) release(*state, state->context->functions());
    delete state;
    return 0;
}

CADENCE_API int cadence_gpu_paint(void* handle, void* painter_pointer,
    const uint8_t* a, const uint8_t* b, int width, int height,
    const uint8_t* lookup, int table_height, uint64_t a_revision, uint64_t b_revision,
    uint64_t table_revision, const double* rectangle, int flip_h, int flip_v, int passthrough, int b_width, int b_height, int layout, int swapped, float wipe,float compare_opacity,float compare_gain) noexcept
{
    auto* state = static_cast<Compositor*>(handle);
    auto* painter = static_cast<QPainter*>(painter_pointer);
    if (!state || !painter || !painter->isActive() || !a || !lookup || !rectangle ||
        width <= 0 || height <= 0 || (table_height != 1 && table_height != 256) ||
        (table_height == 256 && !b) || painter->hasClipping() || painter->opacity() != 1.) return 1;
    if (layout<0 || layout>6 || !std::isfinite(wipe) || !std::isfinite(compare_opacity) || !std::isfinite(compare_gain) || (layout && !b) || (b && (b_width<=0 || b_height<=0))) return 1;
    if (!state->context || state->context != QOpenGLContext::currentContext()) return 2;
    for (int i = 0; i < 4; ++i) if (!std::isfinite(rectangle[i])) return 1;
    if (rectangle[2] <= 0 || rectangle[3] <= 0) return 1;
    try {
        auto* gl = state->context->functions();
        auto stamp = Clock::now();
        auto phase = [&](int index) {
            if (!state->profile) return;
            const auto now = Clock::now();
            timings[index] = std::chrono::duration<double,std::milli>(now-stamp).count();
            stamp = now;
        };
        GLint viewport[4] = {}; gl->glGetIntegerv(GL_VIEWPORT, viewport);
        GLint maximum = 0; gl->glGetIntegerv(GL_MAX_TEXTURE_SIZE, &maximum);
        if (viewport[0] || viewport[1] || viewport[2] <= 0 || viewport[3] <= 0 ||
            width > maximum || height > maximum || b_width > maximum || b_height > maximum) return 1;
        const QTransform transform = painter->deviceTransform();
        const QRectF rect(rectangle[0], rectangle[1], rectangle[2], rectangle[3]);
        const std::array<QPointF,4> corners = {rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()};
        GLfloat vertices[16];
        for (int i = 0; i < 4; ++i) {
            const QPointF point = transform.map(corners[i]);
            vertices[i*4] = GLfloat(point.x()*2./viewport[2]-1.);
            vertices[i*4+1] = GLfloat(1.-point.y()*2./viewport[3]);
            vertices[i*4+2] = GLfloat((i%2) ^ int(!layout && flip_h != 0));
            vertices[i*4+3] = GLfloat((i/2) ^ int(!layout && flip_v != 0));
        }
        NativeScope scope(painter,gl);
        phase(0);
        if (!state->program && !initialize(*state,gl)) return 3;
        phase(1);
        gl->glActiveTexture(GL_TEXTURE0);
        upload(gl,state->textures[0],a,width,height,GL_RGB,a_revision,state->buffered_upload);
        if (passthrough) {
            gl->glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
            gl->glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        }
        phase(2);
        gl->glActiveTexture(GL_TEXTURE1);
        if (b) {
            upload(gl,state->textures[1],b,b_width,b_height,GL_RGB,b_revision,state->buffered_upload);
            if (layout && passthrough) {
                gl->glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);
                gl->glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
            }
        }
        else {
            gl->glBindTexture(GL_TEXTURE_2D,0);
            state->textures[1].revision=0;
        }
        gl->glActiveTexture(GL_TEXTURE2);
        upload(gl,state->textures[2],lookup,256,table_height,GL_RGBA,table_revision);
        phase(3);
        gl->glUseProgram(state->program);
        gl->glUniform1i(gl->glGetUniformLocation(state->program,"imageA"),0);
        gl->glUniform1i(gl->glGetUniformLocation(state->program,"imageB"),1);
        gl->glUniform1i(gl->glGetUniformLocation(state->program,"lookup"),2);
        gl->glUniform2f(state->dimensions,GLfloat(width),GLfloat(height));
        gl->glUniform1i(state->pair,table_height==256);
        gl->glUniform1i(state->passthrough,passthrough != 0);
        gl->glUniform1i(gl->glGetUniformLocation(state->program,"layout"),layout);
        gl->glUniform1i(gl->glGetUniformLocation(state->program,"flipped_h"),flip_h!=0);
        gl->glUniform1i(gl->glGetUniformLocation(state->program,"flipped_v"),flip_v!=0);
        gl->glUniform1i(gl->glGetUniformLocation(state->program,"swapped"),swapped!=0);
        gl->glUniform1f(gl->glGetUniformLocation(state->program,"wipe"),wipe);
        gl->glUniform1f(gl->glGetUniformLocation(state->program,"compare_opacity"),compare_opacity);
        gl->glUniform1f(gl->glGetUniformLocation(state->program,"compare_gain"),compare_gain);
        gl->glUniform2f(gl->glGetUniformLocation(state->program,"b_dimensions"),float(b_width),float(b_height));
        gl->glBindBuffer(GL_ARRAY_BUFFER,state->vertices);
        gl->glBufferData(GL_ARRAY_BUFFER,sizeof(vertices),vertices,GL_STREAM_DRAW);
        gl->glEnableVertexAttribArray(0); gl->glEnableVertexAttribArray(1);
        gl->glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,4*sizeof(GLfloat),nullptr);
        gl->glVertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,4*sizeof(GLfloat),reinterpret_cast<void*>(2*sizeof(GLfloat)));
        gl->glDrawArrays(GL_TRIANGLE_STRIP,0,4);
        phase(4);
        GLenum error = gl->glGetError();
        if (error != GL_NO_ERROR) { failure = "OpenGL compositor error " + std::to_string(error); return 3; }
        return 0;
    } catch (...) { failure = "GPU composition failed"; return 4; }
}

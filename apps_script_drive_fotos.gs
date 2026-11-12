/**
 * Apps Script — recebe foto do app e grava numa pasta do Google Drive.
 *
 * Por que não Google Fotos:
 * A Library API só gerencia mídia criada pelo próprio app e não abre
 * um álbum corporativo compartilhado. A pasta do Drive é o caminho
 * estável. Se o backup do Drive estiver ligado no Google Fotos da conta
 * dona da pasta, as imagens também aparecem em Fotos.
 *
 * Implantação:
 * 1. Crie uma pasta no Drive e copie o ID da URL.
 * 2. Extensões > Apps Script > cole este arquivo.
 * 3. Ajuste PASTA_ID.
 * 4. Implantar > Nova implantação > Aplicativo da Web
 *    Executar como: eu | Quem tem acesso: qualquer pessoa
 * 5. Cole a URL em secrets: DRIVE_WEBHOOK_URL = "https://script.google.com/..."
 *
 * O app envia POST JSON: { chamado_id, tipo, nome, mime, b64 }
 * Resposta: { ok, url, file_id }
 */
var PASTA_ID = "COLE_O_ID_DA_PASTA_DRIVE";

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    var nome = body.nome || ("chamado_" + (body.chamado_id || "x") + ".jpg");
    var mime = body.mime || "image/jpeg";
    var bytes = Utilities.base64Decode(body.b64 || "");
    var blob = Utilities.newBlob(bytes, mime, nome);
    var pasta = DriveApp.getFolderById(PASTA_ID);
    var arquivo = pasta.createFile(blob);
    arquivo.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    return ContentService
      .createTextOutput(JSON.stringify({
        ok: true,
        file_id: arquivo.getId(),
        url: arquivo.getUrl()
      }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, erro: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

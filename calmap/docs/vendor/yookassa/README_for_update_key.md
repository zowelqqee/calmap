[![ЮKassa](/projects/SUP/repos/i/raw/yookassalogo.png "ЮKassa")](https://yookassa.ru) | [помощь](https://yookassa.ru/docs/support)

# Инструкция по обновлению сертификата проверки подписи ответов ЮKassa

Версия документа от 13.11.2025

> **Внимание!** На стороне ЮKassa обновление сертификата будет выполнено 11 декабря 2025 года (четверг) в 11:00 (время московское). Если вы [выполняете проверку подписи ответа ЮKassa](#step3), у вас могут перестать работать ваши выплаты, зачисление на кошелек ЮMoney или процесс идентификации кошелька ЮMoney (в зависимости от того, какой у вас протокол ЮKassa реализован в вашем проекте). Обращаем внимание, что [если вы НЕ проверяете подпись ответа](#donotchecksign), то вам не нужно выполнять никаких действий по текущей инструкции.

> :mortar_board: Для того, чтобы вашему программисту было проще понять, о каком сертификате идет речь, ниже объяснение, где используется этот сертификат, который необходимо обновить. Если вам требуется дополнительная информация, тогда ответьте на полученную рассылку или напишите на адрес b2b_support@yoomoney.ru

### Навигация по текущему документу

* [Документация по протоколам](#документация)
* [Requirements](#requirements)
* [Как обновить сертификат?](#how_to_update_cert)
* [Пример запроса, ответа и проверки подписи](#example)
  * [упаковка запроса](#step1)
  * [отправка упакованного запроса](#step2)
  * [получение ответа и проверка подписи](#step3) *-- эта инструкция как раз про обновление сертификата, с помощью которого выполняется проверка подписи ответа ЮKassa*.
  * [пример, как сконвертировать ответ ЮKassa из base64 в читаемый вид без использования сертификата](#convert_from_base64)

### <a name="документация"></a> Документация по протоколам

* [Протокол выплат](https://yookassa.ru/docs/payouts). Для контрагентов, кто выполняет зачисления на кошельки, карты, р/с или мобильные телефоны.
* [Протокол зачислений](https://yoomoney.ru/docs/depositions). Для контрагентов банков-партнёров.
* `*` Протокол идентификации кошелька направляется контрагентам по запросу (в открытом доступе документации нет).

### <a name="requirements"></a> Requirements

Этот раздел нужен для понимания, что ваши разработчики и команды сделали ранее, чтобы у вас заработал нужный протокол в вашем проекте (список протоколов выше). И именно в этом протоколе используются сертификат, который нужно обновить, о чем и написана эта инструкция.

Для интеграции протокола выплат, зачислений или идентификации, нужно:

1. Зарегистрироваться в ЮKassa как юридическое лицо (или ИП).
2. Сгенерировать CSR запрос по инструкции https://yookassa.ru/docs/payouts/api/using-api/security#creating-csr (см. Получение SSL-сертификата для взаимодействия с серверами ЮКасса) шаги 1-5, передать занный CSR запрос менеджеру ЮKassa и получить в ответ сертификат, с помощью которого вы в дальнейшем будете авторизовываться в нашей системе и упаковывать (шифровать) ваши запросы про протоколу ЮKassa (см. [пример упаковки запроса ниже](#step1)).
3. Получить идентификатор выплатного шлюза (AgentID).
4. Реализовать нужный протокол (api выплат, зачислений или идентификации).

## <a name="how_to_update_cert"></a> Как обновить сертификат?

1. Найдите в вашей системе где размещен текущий сертификат проверки подписи ответа ЮKassa.
2. По ссылке ниже есть копия актуального сертификата (это может помочь в поисках, где размещен такой же файл в вашей системе) и файл нового сертификата:    
[https://git.yoomoney.ru/projects/SUP/repos/certificates/browse/deposit](https://git.yoomoney.ru/projects/SUP/repos/certificates/browse/deposit)  
3. Замените в вашей системе текущий сертификат на новый синхронно с нами, 11 декабря 2025 года (четверг) в 11:00 по московскому времени.

## <a name="example"></a> Пример запроса, ответа и проверки подписи

Этот раздел нужен, чтобы ваш программист прочитав текущий пример взаимодействия, мог вспомнить по коду вашего проекта, как выполняется отправка запроса, получение ответа, преобразование ответа из base64 формата ЮKassa и проверка подписи этого ответа с помощью сертификата, который вы обновляете по этой инструкции.

* Ниже представлен пример запроса makeDeposition с помощью утилиты curl, преобразование полученного ответа из base64-формата c помощью утилиты openssl и [проверка подписи полученного ответа](#step3).
* Раскрытые в документе примеры не заменяют документацию. Они необходимы для случаев, когда программисту контрагента необходимо быстро вспомнить как организован процесс протокольного взаимодействия с ЮKassa. Конечно вы можете работать без утилиты curl и openssl, используя свои инструменты (в данных примерах они используются как наиболее простые для понимания схемы работы).

### <a name="step1"></a> Шаг 1. Упаковка запроса

Сформируйте содержимое запроса и упакуйте его в PKCS7:
```
openssl smime -sign -in req.xml -nointern -nodetach -nocerts -nochain -outform PEM -out req_signed.txt -signer you.cer -inkey private.key -passin pass:HIDDEN
```
* [req.xml](#request) - это тело запроса makeDeposition до упаковки в PKCS7 (см. пример ниже);
* req_signed.txt - упакованный в PKCS7 запрос req.xml;
* you.cer - сертификат, менеджер ЮKassa выдал контрагенту, т.е. вам (см. выше раздел [Requirements](#requirements), п.2);
* private.key - ваш файл секретного ключа, на основе которого вы сделали CSR-запрос, и мы (ЮKassa) на основе него сделали you.cer;
* `-passin` - параметр передается пустым или со значением, в зависимости от того, как вы сделали свой приватный ключ, с паролем или без: `-passin pass:HIDDEN` в запросах: если вы в п.2 (см. выше раздел [Requirements](#requirements)) приватный ключ (private.key) был создан с паролем, то вместо HIDDEN напишите свой пароль, например, `-passin pass:coolpassword`; если без пароля, то передавайте `-passin pass:`, без HIDDEN.
* req_signed.txt - если вы работаете в lunix|unix-системе, то указывайте файл так: `-F file=@req_signed.txt`; в Windows: `--data-ascii @req_signed.txt`.

#### <a name="request"></a> Файл req.xml (тело запроса makeDeposition)
```
<?xml version="1.0" encoding="UTF-8"?>
<makeDepositionRequest agentId="200807" dstAccount="257003392579" requestDT="2020-11-26T12:09:36.000Z" amount="200.00" clientOrderId="7093BCF45E8046ECB675" currency="10643" contract="Договор средств N 123 от 22.08.2020">
        <paymentParams>
                <skr_destinationCardSynonim>dN3VdS7WchWKmWIUfPmcMUUQpikZ.SC.201511</skr_destinationCardSynonim>
                <pdr_birthDate>01.01.2000</pdr_birthDate>
                <pdr_birthPlace>поселок Забайкальского края</pdr_birthPlace>
                <pdr_lastName>Петров</pdr_lastName>
                <pdr_firstName>Андрей</pdr_firstName>
                <pdr_middleName>Александрович</pdr_middleName>
                <pdr_docNumber>123123123</pdr_docNumber>
                <pdr_docIssueYear>2015</pdr_docIssueYear>
                <pdr_docIssueMonth>8</pdr_docIssueMonth>
                <pdr_docIssueDay>12</pdr_docIssueDay>
                <pdr_docIssuedBy>УВД РОВД, город Саратов</pdr_docIssuedBy>
                <pdr_city>Новосибирск</pdr_city>
                <pdr_postcode>630092</pdr_postcode>
                <pdr_address>Новосибирская обл,  Новосибирск,  ул. Ольги Ивановны,  дом N 4,  кв. 5</pdr_address>
                <smsPhoneNumber>79529234933</smsPhoneNumber>
                <pof_offerAccepted>1</pof_offerAccepted>
                <pdr_country>643</pdr_country>
        </paymentParams>
</makeDepositionRequest>
```
#### Возможные ошибки в теле запроса makeDeposition

- Используйте в качестве номера знак N (не используйте спецсимвол №).
- `<paymentParams></paymentParams>`: не забывайте, что все дополнительные параметры (`pdr_birthDate`, `pof_offerAccepted` и т.д.) должны быть внутри paymentParams.

### <a name="step2"></a> Шаг 2. Отправка запроса

Отправьте запрос makeDeposition или makeIdentificationDeposition на сервер payouts.yookassa.ru:
```
curl -X POST --insecure -F file=@req_signed.txt --header "Content-type:application/pkcs7-mime" --cert you.cer --key private.key --pass HIDDEN --url https://payouts.yookassa.ru:9094/webservice/deposition/api/makeDeposition
```

### <a name="step3"></a> Шаг 3. Конвертация ответа из base64 и проверка подписи

В этом разделе вы найдете пример, как работает конвертация ответа из base64 формата и проверка подписи этого ответа.

#### <a name="convert_from_base64"></a> Конвертация ответа ЮKassa из base64-формата

Этот пример показывает, что для конвертации ответа ЮKassa из base64 формата не требуется сертификат. Пример необходим для тех, кто не реализовал в своей системе проверку подписи.

```
$ cat resp.txt | openssl enc -base64 -d | sed -n '/<makeDepositionResponse/,/<\/makeDepositionResponse>/p' | head -1
<makeDepositionResponse clientOrderId="100500700" status="0" processedDT="2023-01-13T17:53:59.943+03:00" balance="-15242.00"></makeDepositionResponse>
```

##### <a name="donotchecksign"></a> Мы не проверяем подпись

Случается, что в вашей системы может быть не реализована проверка подписи (конечно, мы рекомендуем делать так, чтобы проверка выполнялась, но понимаем, что у вас могут быть свои причины, почему в вашей системе это не делается). Если это так, что вам выполнять обновление сертификата по этой инструкции не нужно. Проверяется подпись ответа ЮKassa в вашей системе или нет, знает только ваш разработчик.

#### Проверка подписи

В документации об этом шаге: https://yookassa.ru/docs/payouts/api/using-api/format#response. Не смотря на то, что в документации процесс указан как "проверка подписи", по факту ЮKassa отдает ответ в PKCS7 формате (base64) и чтобы его прочесть вашей системе, требуется вначале сконвертировать ответ из base64 и затем проверить подпись с помощью сертификата (речь об обновлении которого создана эта инструкция).

##### Пример проверки подписи

В примере ниже, файл **deposit.cer** - это и есть нужный вам сертификат, с помощью которого после конвертации ответа ЮKassa из PKCS7 формата, надо выполнять проверку подписи ответа ЮKassa (отметим, что это ответ ЮKassa на ваши запросы makeDeposition или makeIdentificationDeposition):

```
$ openssl smime -verify -noverify -inform PEM -nointern -certfile "deposit.cer" -CAfile "deposit.cer" < resp.txt
	<?xml version="1.0" encoding="UTF-8"?>
	<makeDepositionResponse clientOrderId="12345" status="0" error="30" processedDT="2021-01-21T13:23:07.197+03:00" balance="1000.00" />
	Verification successful
```

В ответе **Verification successful** как раз указывает, что подпись корректна.  
Содержимое файла с ответом ЮKassa на ваш запрос, [resp.txt](#response), см. ниже.

В случае негативного сценария, проверка подписи выдаст значение "Verification failure":
```
$ openssl smime -verify -noverify -inform PEM -nointern -certfile "deposit-incorrect.cer" -CAfile "deposit-incorrect.cer" < resp.txt
	Verification failure
	139971507589568:error:2107C080:PKCS7 routines:PKCS7_get0_signers:signer certificate not found:../crypto/pkcs7/pk7_smime.c:421:
```

Например, негативный ответ "Verification failure", может быть, если сертификат проверки подписи вы не обновили на своей стороне, а ЮKassa обновила этот ключ на своей стороне и поэтому шлет свои ответы с новой подписью.

#### Пример отправки запроса makeDeposition и проверки подписи

1. Отправьте запрос на сервер ("Шаг 2", см. выше) и сохраните полученный ответ в файл resp.txt
`curl -X POST --insecure -F file=@req_signed.txt --header "Content-type:application/pkcs7-mime" --cert you.cer --key private.key --pass HIDDEN --url https://payouts.yookassa.ru:9094/webservice/deposition/api/makeDeposition > resp.txt`

Обратите внимание, что в вашем случае содержимое запроса makeDeposition или makeIdentificationDeposition может быть другим, но это не отменяет того, что ответ ЮKassa на запрос makeDeposition или makeIdentificationDeposition будет в base64 и его необходимо сконвертировать в читаемый вид.
  
2. Выполните проверку подписи полученного ответа (в данном случае из файла resp.txt)
`openssl smime -verify -noverify -inform PEM -nointern -certfile "deposit.cer" -CAfile "deposit.cer" < resp.txt`

Как видно, в проверке подписи используется deposit.cer. Это файл сертификата, с помощью которого нужно выполнить проверку подписи ответа от ЮKassa. Актуальный или новый сертификат можно взять здесь https://git.yoomoney.ru/projects/SUP/repos/certificates/browse/deposit

#### <a name="response"></a> Файл resp.txt

Это пример содержимого ответа ЮKassa из ["Шаг 3, п.1"](#step3).

```
-----BEGIN PKCS7-----
MIAGCSqGSIb3DQEHAqCAMIACAQExCzAJBgUrDgMCGgUAMIAGCSqGSIb3DQEHAaCA
JIAEgcU8ZXJyb3JEZXBvc2l0aW9uTm90aWZpY2F0aW9uUmVxdWVzdCBjbGllbnRP
cmRlcklkPSIyNTNhMzk1Ny0xNjA5LTQ3ODQtYjRlZC1iYjRhNmY2ODgzYzciIHJl
cXVlc3REVD0iMjAxNi0wNC0wNFQxMjowMzowMi43ODlaIiBkc3RBY2NvdW50PSIy
NTcwMDMzOTI1NzkiIGFtb3VudD0iMTM2LjYyIiBjdXJyZW5jeT0iMTA2NDMiIGVy
cm9yPSIzMSIvPgAAAAAAADGCAjcwggIzAgEBMIGEMHwxCzAJBgNVBAYTAlJVMQ8w
DQYDVQQIEwZSdXNzaWExGTAXBgNVBAcTEFNhaW50LVBldGVyc2J1cmcxGDAWBgNV
BAoTD1BTIFlhbmRleC5Nb25leTEQMA4GA1UECxMHVW5rbm93bjEVMBMGA1UEAxMM
WWFuZGV4Lk1vbmV5AgRND18oMAkGBSsOAwIaBQCggYgwGAYJKoZIhvcNAQkDMQsG
CSqGSIb3DQEHATAcBgkqhkiG9w0BCQUxDxcNMTYwNDA0MTIwMzAyWjAjBgkqhkiG
9w0BCQQxFgQUBeVNe6OQrdPV0tgnIMRchvOeMSUwKQYJKoZIhvcNAQk0MRwwGjAJ
BgUrDgMCGgUAoQ0GCSqGSIb3DQEBAQUAMA0GCSqGSIb3DQEBAQUABIIBAJnDA4FJ
w9xd3aH+Q5Zvubrbaf9jci89coST+ySqXbyCI/htgEqHXlapsu256wF+bzTQJM/X
QXj14aP/X7v8JIE937GbldpeyUlWIhbyaw1odL8pnw60nNd9hG11Rav3OmF2l4Xe
jH9VelknKY/IXFWPUK25NkTSHtR28Ze9C1NIE87hmsgq2M6QOnoWITzYL2BM6KtG
1PZKDB0HpqRDw89SjdSeMI+dNet8VSyvmLtR/i8Dr7EWN7+G1tqCi7V4UveWlTKt
O7MZyy3xg64XeaDqG+eD6/3D9GN8Q7J3KDNK9SdjqbmQY6qFCNq1BGEb0zHOs7Ae
9iRii8sV+d9dLywAAAAAAAA=
-----END PKCS7-----
```
Есть вопросы? Пишите на b2b_support@yoomoney.ru

<!--
Это старая часть документации, без правок и поэтому закоментированная, но сохраненная для понимания как мы раньше пытались объяснить этот кейс и как сейчас. Порой помогает понять старые инструкции и ход объяснения в них. Особенно когда мерчант интегрировался по старым инструкциям и как мы его запутали своими инструкциями (ц) Даня Паскаль
===============================================================================================================

### [errorDepositionNotificationRequest](https://yookassa.ru/docs/payouts/api/error-deposition-notification)

Функциональность дешифровки ответа errorDepositionNotificationRequest (ошибки при зачислениях на карты) не относится к "Шагу 3" (см. выше)

```curl -X POST --insecure --data-ascii @req_signed.txt --header "Content-type:application/pkcs7-mime" --url http://app.merchant-site.ru/errorDepositionNotificationRequest
resp.txt
-----BEGIN PKCS7-----
MIAGCSqGSIb3DQEHAqCAMIACAQExCzAJBgUrDgMCGgUAMIAGCSqGSIb3DQEHAaCA
JIAEgcU8ZXJyb3JEZXBvc2l0aW9uTm90aWZpY2F0aW9uUmVxdWVzdCBjbGllbnRP
cmRlcklkPSIyNTNhMzk1Ny0xNjA5LTQ3ODQtYjRlZC1iYjRhNmY2ODgzYzciIHJl
cXVlc3REVD0iMjAxNi0wNC0wNFQxMjowMzowMi43ODlaIiBkc3RBY2NvdW50PSIy
NTcwMDMzOTI1NzkiIGFtb3VudD0iMTM2LjYyIiBjdXJyZW5jeT0iMTA2NDMiIGVy
cm9yPSIzMSIvPgAAAAAAADGCAjcwggIzAgEBMIGEMHwxCzAJBgNVBAYTAlJVMQ8w
DQYDVQQIEwZSdXNzaWExGTAXBgNVBAcTEFNhaW50LVBldGVyc2J1cmcxGDAWBgNV
BAoTD1BTIFlhbmRleC5Nb25leTEQMA4GA1UECxMHVW5rbm93bjEVMBMGA1UEAxMM
WWFuZGV4Lk1vbmV5AgRND18oMAkGBSsOAwIaBQCggYgwGAYJKoZIhvcNAQkDMQsG
CSqGSIb3DQEHATAcBgkqhkiG9w0BCQUxDxcNMTYwNDA0MTIwMzAyWjAjBgkqhkiG
9w0BCQQxFgQUBeVNe6OQrdPV0tgnIMRchvOeMSUwKQYJKoZIhvcNAQk0MRwwGjAJ
BgUrDgMCGgUAoQ0GCSqGSIb3DQEBAQUAMA0GCSqGSIb3DQEBAQUABIIBAJnDA4FJ
w9xd3aH+Q5Zvubrbaf9jci89coST+ySqXbyCI/htgEqHXlapsu256wF+bzTQJM/X
QXj14aP/X7v8JIE937GbldpeyUlWIhbyaw1odL8pnw60nNd9hG11Rav3OmF2l4Xe
jH9VelknKY/IXFWPUK25NkTSHtR28Ze9C1NIE87hmsgq2M6QOnoWITzYL2BM6KtG
1PZKDB0HpqRDw89SjdSeMI+dNet8VSyvmLtR/i8Dr7EWN7+G1tqCi7V4UveWlTKt
O7MZyy3xg64XeaDqG+eD6/3D9GN8Q7J3KDNK9SdjqbmQY6qFCNq1BGEb0zHOs7Ae
9iRii8sV+d9dLywAAAAAAAA=
-----END PKCS7-----```

#### Дешифровка ответа
```curl -X POST --insecure --data-ascii @req_signed.txt --header "Content-type:application/pkcs7-mime" --url https://app/ya/errorDepositionNotificationRequest<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN">
<html><head>
<title>403 Forbidden</title>
</head><body>
<h1>Forbidden</h1>
<p>You don't have permission to access /errorDepositionNotificationRequest
on this server.</p>
</body></html>```

==========

### Старый пример в одну строку

```A=$(echo "<makeDepositionRequest agentId=\"0000\" clientOrderId=\"123\" requestDT=\"`date +%Y-%m-%dT%H:%M:%S`\" dstAccount=\"257003392579\" amount=\"110.00\" currency=\"10643\" contract=\"test_test\"><paymentParams><skr_destinationCardSynonim>7yJteyIZuXB4B6mOMurvxyAjUKAZ.SC.201710</skr_destinationCardSynonim><pdr_firstName>Гнилица</pdr_firstName><pdr_middleName>Иван</pdr_middleName><pdr_lastName>Иванов</pdr_lastName><pdr_docNumber>1111111111</pdr_docNumber><pdr_postcode>020202</pdr_postcode><pdr_country>643</pdr_country><pdr_city>Город</pdr_city><pdr_address>улица улица1</pdr_address><pdr_birthDate>01.01.1990</pdr_birthDate><pdr_birthPlace>Город</pdr_birthPlace><pdr_docIssueYear>2008</pdr_docIssueYear><pdr_docIssueMonth>01</pdr_docIssueMonth><pdr_docIssueDay>10</pdr_docIssueDay><pdr_docIssuedBy>ОВД г. улица</pdr_docIssuedBy><pof_offerAccepted>1</pof_offerAccepted><smsPhoneNumber>7999999999</smsPhoneNumber></paymentParams></makeDepositionRequest>" | openssl smime -sign -signer /var/www/www-root/data/www/apikassa.tk/KeysForApi/gnilitsa_gates.cer -inkey /var/www/www-root/data/www/apikassa.tk/KeysForApi/private.key -nochain -nocerts -outform PEM -nodetach -passin pass:*****) && curl -v -H "Content-Type: application/pkcs7-mime" -k --cert /var/www/www-root/data/www/apikassa.tk/KeysForApi/gnilitsa_gates.cer --key /var/www/www-root/data/www/apikassa.tk/KeysForApi/private.key --pass ***** --request POST "https://payouts.yookassa.ru:9094/webservice/deposition/api/makeDeposition" --data "$A"
```
--> 
